"""Quote Verifier — Document Index.

Inverted word-position index for fast quote lookup.
Build once per document, query many times.
"""

import base64
import logging
import zlib
from array import array
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterator, Mapping
from typing import Dict, List, Tuple

from .config import MatchStrategy, QuoteVerifierConfig
from .normalizer import normalize_with_mapping
from .posmap import U32, RunMap
from .vocab import Vocab

log = logging.getLogger("parseltongue.quote_verifier")


def _content_hash(text: str) -> str:
    return format(zlib.crc32(text.encode()), "08x")


def remap_csr(terms: array, offsets: array, values: array, id_remap: array) -> tuple[array, array, array]:
    """Translate a CSR (sorted term ids, offsets, values) through *id_remap*.

    Ids change, so the term order may change; the value runs are permuted
    along with their terms so the layout stays contiguous and sorted.
    """
    order = sorted(range(len(terms)), key=lambda k: id_remap[terms[k]])
    new_terms = array(U32, (id_remap[terms[k]] for k in order))
    new_offsets = array(U32, [0])
    new_values = array(U32)
    for k in order:
        new_values.extend(values[offsets[k] : offsets[k + 1]])
        new_offsets.append(len(new_values))
    return new_terms, new_offsets, new_values


class TermPositions(Mapping[str, array]):
    """Read-only ``word → positions`` view over a document's id arrays.

    Backed by three arrays on the document: sorted term ids, a CSR-style
    offsets table, and the flat position list. Values are ``array('I')``
    slices — iterate them or take ``len()`` exactly like the lists they
    replace.
    """

    __slots__ = ("_doc",)

    def __init__(self, doc: "IndexedDocument"):
        self._doc = doc

    def _slot(self, word: str) -> int:
        tid = self._doc.vocab.lookup(word)
        if tid is None:
            return -1
        terms = self._doc._wp_terms
        k = bisect_left(terms, tid)
        if k < len(terms) and terms[k] == tid:
            return k
        return -1

    def _positions(self, k: int) -> array:
        off = self._doc._wp_offsets
        return self._doc._wp_positions[off[k] : off[k + 1]]

    def __getitem__(self, word: str) -> array:
        k = self._slot(word)
        if k < 0:
            raise KeyError(word)
        return self._positions(k)

    def __contains__(self, word: object) -> bool:
        return isinstance(word, str) and self._slot(word) >= 0

    def __iter__(self) -> Iterator[str]:
        vocab = self._doc.vocab
        for tid in self._doc._wp_terms:
            yield vocab.term(tid)

    def __len__(self) -> int:
        return len(self._doc._wp_terms)

    def items(self):
        vocab = self._doc.vocab
        off = self._doc._wp_offsets
        pos = self._doc._wp_positions
        for k, tid in enumerate(self._doc._wp_terms):
            yield vocab.term(tid), pos[off[k] : off[k + 1]]


class IndexedDocument:
    """A single document's pre-processed data with word-position index.

    Everything positional is an ``array('I')`` or a :class:`RunMap`; the
    only per-document Python objects are the two text strings and a
    handful of containers, whatever the document size.
    """

    __slots__ = (
        "name",
        "original_text",
        "normalized_text",
        "position_map",
        "content_hash",
        "vocab",
        "_wp_terms",
        "_wp_offsets",
        "_wp_positions",
        "_collapsed_text",
        "_collapsed_to_norm",
    )

    #: Blob keys emitted by :meth:`to_record`, in a fixed order.
    BLOB_KEYS = ("nt", "pm.s", "pm.v", "wt", "wo", "wp")

    def __init__(self, name: str, text: str, config: QuoteVerifierConfig, vocab: Vocab | None = None):
        self.name = name
        self.original_text = text
        self.content_hash = _content_hash(text)
        self.vocab = vocab if vocab is not None else Vocab()
        normalized, pos_map, _ = normalize_with_mapping(text, config)
        self.normalized_text = normalized
        self.position_map = RunMap.from_seq(pos_map)
        self._wp_terms, self._wp_offsets, self._wp_positions = self._build_word_index()
        self._collapsed_text: str | None = None
        self._collapsed_to_norm: RunMap | None = None

    @property
    def word_positions(self) -> TermPositions:
        """``word → array of start positions in normalized_text``."""
        return TermPositions(self)

    # ── persistence ──

    def to_record(self) -> tuple[dict, dict[str, bytes]]:
        """(meta, blobs) for the cache. Ids in the blobs are relative to
        ``self.vocab`` — the owner persists the term list alongside."""
        pm_starts, pm_values = self.position_map.to_blobs()
        meta = {
            "name": self.name,
            "content_hash": self.content_hash,
            "norm_len": len(self.position_map),
        }
        blobs = {
            "nt": self.normalized_text.encode("utf-8"),
            "pm.s": pm_starts,
            "pm.v": pm_values,
            "wt": self._wp_terms.tobytes(),
            "wo": self._wp_offsets.tobytes(),
            "wp": self._wp_positions.tobytes(),
        }
        return meta, blobs

    @classmethod
    def from_record(
        cls,
        original_text: str,
        meta: dict,
        blobs: Mapping[str, bytes | memoryview],
        vocab: Vocab,
        id_remap: array | None = None,
    ) -> "IndexedDocument":
        """Restore from :meth:`to_record` output.

        ``id_remap`` translates the cache's term ids into *vocab*'s ids when
        the cache was written against a different term list.
        """
        obj = object.__new__(cls)
        obj.name = meta["name"]
        obj.original_text = original_text
        obj.content_hash = _content_hash(original_text)
        obj.vocab = vocab
        obj.normalized_text = bytes(blobs["nt"]).decode("utf-8")
        obj.position_map = RunMap.from_blobs(blobs["pm.s"], blobs["pm.v"], meta["norm_len"])
        terms = array(U32)
        terms.frombytes(blobs["wt"])
        offsets = array(U32)
        offsets.frombytes(blobs["wo"])
        positions = array(U32)
        positions.frombytes(blobs["wp"])
        if id_remap is not None:
            terms, offsets, positions = remap_csr(terms, offsets, positions, id_remap)
        obj._wp_terms = terms
        obj._wp_offsets = offsets
        obj._wp_positions = positions
        obj._collapsed_text = None
        obj._collapsed_to_norm = None
        return obj

    # ── index construction ──

    def _build_word_index(self) -> tuple[array, array, array]:
        """CSR layout of ``term id → start positions`` over normalized text.

        Returns (sorted term ids, offsets[len+1], positions). Positions of
        one term are ascending because the scan is left-to-right.
        """
        by_id: Dict[int, List[int]] = defaultdict(list)
        text = self.normalized_text
        vocab_id = self.vocab.id
        i = 0
        n = len(text)

        while i < n:
            # Skip whitespace
            while i < n and text[i] == " ":
                i += 1
            if i >= n:
                break
            # Collect word
            start = i
            while i < n and text[i] != " ":
                i += 1
            word = text[start:i]
            if word:
                by_id[vocab_id(word)].append(start)

        terms = array(U32, sorted(by_id))
        offsets = array(U32, [0])
        positions = array(U32)
        for tid in terms:
            positions.extend(by_id[tid])
            offsets.append(len(positions))
        return terms, offsets, positions

    def _collapsed(self) -> tuple[str, RunMap]:
        """Space-collapsed normalized_text + map back to normalized positions.

        Fallback for quotes that miss the primary index because the source
        has spurious spaces inside words (PDF line breaks). Built on first
        use and kept; never persisted — it is derivable in one pass.
        """
        if self._collapsed_text is None or self._collapsed_to_norm is None:
            collapsed = []
            mapping = []
            for i, ch in enumerate(self.normalized_text):
                if ch != " ":
                    collapsed.append(ch)
                    mapping.append(i)
            self._collapsed_text = "".join(collapsed)
            self._collapsed_to_norm = RunMap.from_seq(mapping)
        return self._collapsed_text, self._collapsed_to_norm

    def find(self, normalized_quote: str) -> Tuple[int, int, MatchStrategy]:
        """Find first quote position. Back-compat wrapper around find_all.

        Returns (start, end, strategy). (-1, -1, NONE) if not found.
        """
        matches = self.find_all(normalized_quote)
        if matches:
            return matches[0]
        return -1, -1, MatchStrategy.NONE

    def find_all(self, normalized_quote: str) -> List[Tuple[int, int, MatchStrategy]]:
        """Find all positions of a quote in the document.

        Returns exact matches first, then collapsed matches.
        Each entry is (start, end, strategy).
        """
        if not normalized_quote:
            return []

        results: List[Tuple[int, int, MatchStrategy]] = []

        for start, end in self._find_all_exact(normalized_quote):
            results.append((start, end, MatchStrategy.EXACT))

        if not results:
            for start, end in self._find_all_collapsed(normalized_quote):
                results.append((start, end, MatchStrategy.COLLAPSED))

        return results

    def _find_all_exact(self, normalized_quote: str) -> List[Tuple[int, int]]:
        """Find all exact matches via inverted word-position index."""
        space_idx = normalized_quote.find(" ")
        first_word = normalized_quote[:space_idx] if space_idx != -1 else normalized_quote

        candidates = self.word_positions.get(first_word)
        if not candidates:
            return []

        quote_len = len(normalized_quote)
        text = self.normalized_text
        text_len = len(text)
        results = []

        for pos in candidates:
            if pos + quote_len <= text_len:
                if text[pos : pos + quote_len] == normalized_quote:
                    results.append((pos, pos + quote_len - 1))

        return results

    def _find_all_collapsed(self, normalized_quote: str) -> List[Tuple[int, int]]:
        """Find all collapsed matches (spaces removed from both sides).

        Handles PDF line-break artifacts where source has spurious spaces
        inside words that the quote doesn't.
        """
        collapsed_quote = normalized_quote.replace(" ", "")
        if not collapsed_quote:
            return []

        results = []
        offset = 0
        ctext, to_norm = self._collapsed()
        clen = len(collapsed_quote)

        while offset <= len(ctext) - clen:
            idx = ctext.find(collapsed_quote, offset)
            if idx == -1:
                break
            start = to_norm[idx]
            end = to_norm[idx + clen - 1]
            results.append((start, end))
            offset = idx + 1

        return results


class DocumentIndex:
    """Registry of indexed documents. Build once, query by name."""

    def __init__(
        self,
        documents: Dict[str, str] | None = None,
        config: QuoteVerifierConfig | None = None,
    ):
        self.config = config or QuoteVerifierConfig()
        self.vocab = Vocab()
        self.documents: Dict[str, IndexedDocument] = {}
        self._hashes: Dict[str, str] = {}
        self._merged: Dict[str, List[Tuple[str, int]]] | None = None
        # Quote provenance: (doc_name, start, end) → caller_name
        self._quote_ranges: List[Tuple[str, int, int, str]] = []  # (doc, start, end, caller)

        if documents:
            for name, text in documents.items():
                self.add(name, text)

    def add(self, name: str, text: str) -> IndexedDocument:
        """Index a document. Skips re-indexing if content hash matches.

        COW: builds a new documents dict so concurrent readers iterating
        the old dict are never disturbed.
        """
        h = _content_hash(text)
        if name in self._hashes and self._hashes[name] == h and name in self.documents:
            return self.documents[name]
        doc = IndexedDocument(name, text, self.config, self.vocab)
        # COW swap — readers holding the old dict ref see a consistent view.
        new_docs = dict(self.documents)
        new_docs[name] = doc
        new_hashes = dict(self._hashes)
        new_hashes[name] = h
        self.documents = new_docs
        self._hashes = new_hashes
        self._invalidate_merged()
        return doc

    def get(self, name: str) -> IndexedDocument:
        """Get an indexed document by name. Raises KeyError if not found."""
        if name not in self.documents:
            raise KeyError(f"Document not indexed: {name}")
        return self.documents[name]

    def find_in(self, name: str, normalized_quote: str) -> Tuple[int, int, MatchStrategy]:
        """Find a normalized quote in a named document. Returns (-1, -1) if not found."""
        return self.get(name).find(normalized_quote)

    def to_record(self) -> tuple[dict, dict[str, bytes]]:
        """Serialize index as (meta, blobs): the term list, per-document
        normalized text + position maps + word positions, content hashes.

        Quote ranges are NOT serialized — they are rebuilt on load
        via _verify_evidence calls.
        """
        docs_meta = []
        blobs: dict[str, bytes] = {}
        for i, (name, doc) in enumerate(self.documents.items()):
            meta, doc_blobs = doc.to_record()
            docs_meta.append(meta)
            for key, blob in doc_blobs.items():
                blobs[f"{i}.{key}"] = blob
        return {
            "vocab": list(self.vocab.terms),
            "documents": docs_meta,
            "hashes": dict(self._hashes),
        }, blobs

    @classmethod
    def from_record(
        cls,
        meta: dict,
        blobs: Mapping[str, bytes | memoryview],
        original_texts: Dict[str, str],
        config: QuoteVerifierConfig | None = None,
    ) -> "DocumentIndex":
        """Restore index from :meth:`to_record` output + original texts.

        Documents whose content hash no longer matches are re-indexed.
        """
        idx = cls(config=config)
        idx.vocab = Vocab(meta.get("vocab", ()))
        saved_hashes = meta.get("hashes", {})

        for i, doc_meta in enumerate(meta.get("documents", [])):
            name = doc_meta["name"]
            original = original_texts.get(name, "")
            saved_hash = saved_hashes.get(name, "")
            current_hash = _content_hash(original) if original else ""

            if saved_hash and saved_hash == current_hash:
                # Content unchanged — restore from the record
                doc_blobs = {key: blobs[f"{i}.{key}"] for key in IndexedDocument.BLOB_KEYS}
                idx.documents[name] = IndexedDocument.from_record(original, doc_meta, doc_blobs, idx.vocab)
                idx._hashes[name] = saved_hash
            else:
                # Content changed — re-index
                idx.add(name, original)

        return idx

    # JSON-embeddable form of the record, for callers that persist the
    # index inside a larger JSON document (System caches). Blobs ride as
    # base64 — fine for the handful of evidence documents a .pltg cites;
    # corpus-scale indexes go through to_record()/BlobPGZ.

    def to_dict(self) -> dict:
        meta, blobs = self.to_record()
        meta["blobs"] = {k: base64.b64encode(v).decode("ascii") for k, v in blobs.items()}
        return meta

    @classmethod
    def from_dict(
        cls, data: dict, original_texts: Dict[str, str], config: QuoteVerifierConfig | None = None
    ) -> "DocumentIndex":
        """Restore from :meth:`to_dict`. Any other layout (a cache written by
        an earlier schema) is rebuilt from *original_texts* instead."""
        if "blobs" not in data or "vocab" not in data:
            return cls(documents=dict(original_texts), config=config)
        blobs = {k: base64.b64decode(v) for k, v in data["blobs"].items()}
        meta = {k: v for k, v in data.items() if k != "blobs"}
        return cls.from_record(meta, blobs, original_texts, config=config)

    def refresh_document(self, name: str, new_text: str) -> int:
        """Re-index a document and recompute quote positions.

        Extracts quote text from the old normalized content, re-indexes the
        document with new_text, and re-finds each quote at its new position.
        Returns the number of quotes that could not be relocated.
        """
        old_doc = self.documents.get(name)
        if old_doc is None:
            self.add(name, new_text)
            return 0

        # Extract quote text from old normalized content
        affected = [(i, r) for i, r in enumerate(self._quote_ranges) if r[0] == name]
        if not affected:
            self.add(name, new_text)
            return 0

        old_quotes = []
        for idx, (doc, start, end, caller) in affected:
            quote_text = old_doc.normalized_text[start : end + 1]
            old_quotes.append((idx, quote_text, caller))

        # Re-index with new content
        self.add(name, new_text)
        new_doc = self.documents[name]

        # Re-find quotes at new positions
        lost = 0
        for idx, quote_text, caller in old_quotes:
            new_start, new_end, strategy = new_doc.find(quote_text)
            if new_start == -1:
                lost += 1
                self._quote_ranges[idx] = (name, -1, -1, caller)
            else:
                self._quote_ranges[idx] = (name, new_start, new_end, caller)

        # Clean up unfound quotes
        if lost:
            self._quote_ranges = [r for r in self._quote_ranges if r[1] != -1]

        return lost

    # ── Quote provenance ──

    def register_quote(self, doc_name: str, start: int, end: int, caller: str):
        """Record that caller owns the range [start, end] in doc_name.

        COW: builds a new list so concurrent readers are undisturbed.
        """
        self._quote_ranges = [*self._quote_ranges, (doc_name, start, end, caller)]
        if len(self._quote_ranges) % 500 == 0:
            log.debug("register_quote: %d ranges total (latest: %s in %s)", len(self._quote_ranges), caller, doc_name)

    def trace(self, query: str, max_results: int = 10000) -> List[Dict]:
        """Search text across all documents and find pltg nodes whose quotes overlap.

        Returns list of {document, line, column, context, caller, overlap} dicts,
        ranked by overlap ratio (how much of the query the quote covers).
        """
        from .normalizer import normalize_with_mapping

        norm_query, _, _ = normalize_with_mapping(query, self.config)
        if not norm_query.strip():
            return []

        results = []
        documents = self.documents  # grab once — COW safe
        quote_ranges = self._quote_ranges
        for doc_name, doc in documents.items():
            # Find all occurrences of query in this document
            text = doc.normalized_text
            qlen = len(norm_query)
            offset = 0
            while offset <= len(text) - qlen:
                pos = text.find(norm_query, offset)
                if pos == -1:
                    break
                # Map to original positions
                orig_start = doc.position_map[pos] if pos < len(doc.position_map) else pos
                orig_end = doc.position_map[min(pos + qlen - 1, len(doc.position_map) - 1)]

                # Find quote ranges that contain this match
                for r_doc, r_start, r_end, caller in quote_ranges:
                    if r_doc != doc_name:
                        continue
                    # Match must fall within (or overlap) the quote range
                    if orig_end < r_start or orig_start > r_end:
                        continue
                    # Overlap = fraction of query covered by quote
                    overlap_start = max(orig_start, r_start)
                    overlap_end = min(orig_end, r_end)
                    overlap_len = overlap_end - overlap_start + 1
                    query_len = orig_end - orig_start + 1
                    overlap_ratio = overlap_len / query_len if query_len > 0 else 0

                    line = doc.original_text[:orig_start].count("\n") + 1
                    line_start = doc.original_text.rfind("\n", 0, orig_start) + 1
                    line_end = doc.original_text.find("\n", orig_start)
                    if line_end == -1:
                        line_end = len(doc.original_text)
                    context = doc.original_text[line_start:line_end]

                    results.append(
                        {
                            "document": doc_name,
                            "line": line,
                            "column": orig_start - line_start + 1,
                            "context": context,
                            "caller": caller,
                            "overlap": round(overlap_ratio, 3),
                        }
                    )
                offset = pos + 1
            if len(results) >= max_results:
                break

        return results[:max_results]

    # ── Full-text search across all documents ──

    def _merged_index(self) -> Dict[str, List[Tuple[str, int]]]:
        """Lazily build merged inverted index: word → [(doc_name, pos), ...]."""
        if hasattr(self, "_merged") and self._merged is not None:
            return self._merged
        merged: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        documents = self.documents  # grab once — COW safe
        for name, doc in documents.items():
            for word, positions in doc.word_positions.items():
                for pos in positions:
                    merged[word].append((name, pos))
        self._merged = dict(merged)
        return self._merged

    def _invalidate_merged(self):
        self._merged = None

    def search(self, query: str, max_results: int = 10000) -> List[Dict]:
        """Search for a phrase across all indexed documents.

        Returns list of {document, line, column, context} dicts,
        sorted by (document, line).
        """
        from .normalizer import normalize_with_mapping

        norm_query, _, _ = normalize_with_mapping(query, self.config)
        if not norm_query.strip():
            return []

        results = []
        documents = self.documents  # grab once — COW safe
        for name, doc in documents.items():
            start, end, strategy = doc.find(norm_query)
            if start == -1:
                continue
            # Find all occurrences, not just the first
            offset = 0
            text = doc.normalized_text
            qlen = len(norm_query)
            while offset <= len(text) - qlen:
                pos = text.find(norm_query, offset)
                if pos == -1:
                    break
                orig_pos = doc.position_map[pos] if pos < len(doc.position_map) else pos
                line = doc.original_text[:orig_pos].count("\n") + 1
                line_start = doc.original_text.rfind("\n", 0, orig_pos) + 1
                col = orig_pos - line_start + 1
                # Extract context line
                line_end = doc.original_text.find("\n", orig_pos)
                if line_end == -1:
                    line_end = len(doc.original_text)
                context = doc.original_text[line_start:line_end]
                results.append(
                    {
                        "document": name,
                        "line": line,
                        "column": col,
                        "context": context,
                    }
                )
                offset = pos + 1
                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break

        results.sort(key=lambda r: (r["document"], r["line"]))
        return results[:max_results]

    def search_word(self, word: str, max_results: int = 10000) -> List[Dict]:
        """Search for a single word across all documents using the merged inverted index.

        Faster than search() for single-word lookups.
        Returns list of {document, line, column, context} dicts.
        """
        from .normalizer import normalize_with_mapping

        norm_word, _, _ = normalize_with_mapping(word, self.config)
        norm_word = norm_word.strip()
        if not norm_word or " " in norm_word:
            return self.search(word, max_results)

        merged = self._merged_index()
        hits = merged.get(norm_word, [])
        results = []
        for doc_name, pos in hits:
            doc = self.documents[doc_name]
            orig_pos = doc.position_map[pos] if pos < len(doc.position_map) else pos
            line = doc.original_text[:orig_pos].count("\n") + 1
            line_start = doc.original_text.rfind("\n", 0, orig_pos) + 1
            col = orig_pos - line_start + 1
            line_end = doc.original_text.find("\n", orig_pos)
            if line_end == -1:
                line_end = len(doc.original_text)
            context = doc.original_text[line_start:line_end]
            results.append(
                {
                    "document": doc_name,
                    "line": line,
                    "column": col,
                    "context": context,
                }
            )
            if len(results) >= max_results:
                break
        results.sort(key=lambda r: (r["document"], r["line"]))
        return results[:max_results]

    def words(self, min_count: int = 1) -> Dict[str, int]:
        """Return word frequencies across all documents.

        Useful for vocabulary exploration. Words appearing in fewer
        than min_count documents are excluded.
        """
        merged = self._merged_index()
        freq: Dict[str, int] = {}
        for word, hits in merged.items():
            docs = {doc_name for doc_name, _ in hits}
            if len(docs) >= min_count:
                freq[word] = len(hits)
        return dict(sorted(freq.items(), key=lambda x: -x[1]))

    def __contains__(self, name: str) -> bool:
        return name in self.documents

    def __len__(self) -> int:
        return len(self.documents)
