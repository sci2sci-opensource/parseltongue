"""Quote Verifier — Document Index.

Inverted word-position index for fast quote lookup.
Build once per document, query many times.
"""

import hashlib
from collections import defaultdict
from typing import Dict, List, Tuple

from .config import MatchStrategy, QuoteVerifierConfig
from .normalizer import normalize_with_mapping


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class IndexedDocument:
    """A single document's pre-processed data with word-position index."""

    __slots__ = (
        "name",
        "original_text",
        "normalized_text",
        "position_map",
        "word_positions",
        "_collapsed_text",
        "_collapsed_to_norm",
    )

    def __init__(self, name: str, text: str, config: QuoteVerifierConfig):
        self.name = name
        self.original_text = text
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
        """Find quote position using the inverted index.

        Falls back to space-collapsed matching for cases like
        "diphe nyltetrazolium" in source vs "diphenyltetrazolium" in quote.

        Returns (start, end, strategy). (-1, -1, NONE) if not found.
        """
        if not normalized_quote:
            return -1, -1, MatchStrategy.NONE

        result = self._find_exact(normalized_quote)
        if result[0] != -1:
            return result[0], result[1], MatchStrategy.EXACT

        result = self._find_collapsed(normalized_quote)
        if result[0] != -1:
            return result[0], result[1], MatchStrategy.COLLAPSED

        return -1, -1, MatchStrategy.NONE

    def _find_exact(self, normalized_quote: str) -> Tuple[int, int]:
        """Primary lookup via inverted word-position index."""
        space_idx = normalized_quote.find(" ")
        first_word = normalized_quote[:space_idx] if space_idx != -1 else normalized_quote

        candidates = self.word_positions.get(first_word)
        if not candidates:
            return -1, -1

        quote_len = len(normalized_quote)
        text = self.normalized_text
        text_len = len(text)

        for pos in candidates:
            if pos + quote_len <= text_len:
                if text[pos : pos + quote_len] == normalized_quote:
                    return pos, pos + quote_len - 1

        return -1, -1

    def _find_collapsed(self, normalized_quote: str) -> Tuple[int, int]:
        """Fallback: match with all spaces removed from both sides.

        Handles PDF line-break artifacts where source has spurious spaces
        inside words that the quote doesn't.
        """
        collapsed_quote = normalized_quote.replace(" ", "")
        if not collapsed_quote:
            return -1, -1

        idx = self._collapsed_text.find(collapsed_quote)
        if idx == -1:
            return -1, -1

        # Map start and end back to normalized_text positions
        start = self._collapsed_to_norm[idx]
        end = self._collapsed_to_norm[idx + len(collapsed_quote) - 1]
        return start, end


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
        """Index a document. Skips re-indexing if content hash matches."""
        h = _content_hash(text)
        if name in self._hashes and self._hashes[name] == h:
            return self.documents[name]
        doc = IndexedDocument(name, text, self.config)
        self.documents[name] = doc
        self._hashes[name] = h
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

    # ── Quote provenance ──

    def register_quote(self, doc_name: str, start: int, end: int, caller: str):
        """Record that caller owns the range [start, end] in doc_name."""
        self._quote_ranges.append((doc_name, start, end, caller))

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
        for doc_name, doc in self.documents.items():
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
                for r_doc, r_start, r_end, caller in self._quote_ranges:
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
        for name, doc in self.documents.items():
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
        for name, doc in self.documents.items():
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
