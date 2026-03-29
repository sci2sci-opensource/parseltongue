"""Quote Verifier — Document Index.

Inverted word-position index for fast quote lookup.
Build once per document, query many times.
"""

import logging
import zlib
from collections import defaultdict
from typing import Dict, List, Tuple

from .config import MatchStrategy, QuoteVerifierConfig
from .normalizer import normalize_with_mapping

log = logging.getLogger("parseltongue.quote_verifier")


def _content_hash(text: str) -> str:
    return format(zlib.crc32(text.encode()), "08x")


class IndexedDocument:
    """A single document's pre-processed data with word-position index."""

    __slots__ = (
        "name",
        "original_text",
        "normalized_text",
        "position_map",
        "word_positions",
        "content_hash",
        "_collapsed_text",
        "_collapsed_to_norm",
    )

    def __init__(self, name: str, text: str, config: QuoteVerifierConfig):
        self.name = name
        self.original_text = text
        self.content_hash = _content_hash(text)
        self.normalized_text, self.position_map, _ = normalize_with_mapping(text, config)
        self.word_positions = self._build_word_index()
        self._collapsed_text, self._collapsed_to_norm = self._build_collapsed()

    @classmethod
    def from_serialized(
        cls, name: str, original_text: str, normalized_text: str, position_map: List[int]
    ) -> "IndexedDocument":
        """Restore from serialized state — skips normalize_with_mapping."""
        obj = object.__new__(cls)
        obj.name = name
        obj.original_text = original_text
        obj.content_hash = _content_hash(original_text)
        obj.normalized_text = normalized_text
        obj.position_map = position_map
        obj.word_positions = obj._build_word_index()
        obj._collapsed_text, obj._collapsed_to_norm = obj._build_collapsed()
        return obj

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "normalized_text": self.normalized_text,
            "position_map": self.position_map,
            "content_hash": self.content_hash,
        }

    def _build_word_index(self) -> Dict[str, List[int]]:
        """Map each word to its character start positions in normalized text."""
        index: Dict[str, List[int]] = defaultdict(list)
        text = self.normalized_text
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
                index[word].append(start)

        return dict(index)

    def _build_collapsed(self):
        """Build a space-collapsed version of normalized_text.

        Used as fallback when the primary index misses due to spurious
        spaces in the source (e.g. PDF line-break inside a word).

        Returns (collapsed_text, collapsed_to_norm) where
        collapsed_to_norm[i] is the position in normalized_text.
        """
        collapsed = []
        mapping = []
        for i, ch in enumerate(self.normalized_text):
            if ch != " ":
                collapsed.append(ch)
                mapping.append(i)
        return "".join(collapsed), mapping

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
        ctext = self._collapsed_text
        clen = len(collapsed_quote)

        while offset <= len(ctext) - clen:
            idx = ctext.find(collapsed_quote, offset)
            if idx == -1:
                break
            start = self._collapsed_to_norm[idx]
            end = self._collapsed_to_norm[idx + clen - 1]
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
        doc = IndexedDocument(name, text, self.config)
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

    def to_dict(self) -> dict:
        """Serialize index: normalized text + position maps + content hashes.

        Quote ranges are NOT serialized — they are rebuilt on load
        via _verify_evidence calls.
        """
        return {
            "documents": {name: doc.to_dict() for name, doc in self.documents.items()},
            "hashes": dict(self._hashes),
        }

    @classmethod
    def from_dict(
        cls, data: dict, original_texts: Dict[str, str], config: QuoteVerifierConfig | None = None
    ) -> "DocumentIndex":
        """Restore index from serialized state + original texts.

        Documents whose content hash no longer matches are re-indexed.
        """
        idx = cls(config=config)
        docs_data = data.get("documents", data)  # compat: old format had docs at top level
        saved_hashes = data.get("hashes", {})

        for name, doc_data in docs_data.items():
            original = original_texts.get(name, "")
            saved_hash = saved_hashes.get(name, "")
            current_hash = _content_hash(original) if original else ""

            if saved_hash and saved_hash == current_hash:
                # Content unchanged — restore from serialized
                idx.documents[name] = IndexedDocument.from_serialized(
                    name=doc_data["name"],
                    original_text=original,
                    normalized_text=doc_data["normalized_text"],
                    position_map=doc_data["position_map"],
                )
                idx._hashes[name] = saved_hash
            else:
                # Content changed — re-index
                idx.add(name, original)

        return idx

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
