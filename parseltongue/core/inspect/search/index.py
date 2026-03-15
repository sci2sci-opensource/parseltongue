"""DocumentSearchIndex — search-level index wrapping DocumentIndex.

Creates a SearchDocument per IndexedDocument, providing line-level
word, stem, and n-gram indices on top of the existing character-level
inverted index.

This is the entry point for the strategy cascade and the (strategy ...)
operator in the search system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .document import SearchDocument

if TYPE_CHECKING:
    from parseltongue.core.quote_verifier.index import DocumentIndex


class DocumentSearchIndex:
    """Search-level index over a DocumentIndex.

    Wraps each IndexedDocument in a SearchDocument (line-level indices)
    and exposes the strategy dispatch for queries.
    """

    __slots__ = ("_doc_index", "documents", "_quote_by_doc", "_quote_starts")

    def __init__(self, doc_index: "DocumentIndex"):
        self._doc_index = doc_index
        self.documents: dict[str, SearchDocument] = {}
        self._quote_by_doc: dict[str, list[tuple[int, int, str]]] | None = None
        self._quote_starts: dict[str, list[int]] | None = None
        self._build()

    def _build(self):
        """Create SearchDocument wrappers for all indexed documents."""
        for name, doc in self._doc_index.documents.items():
            self.documents[name] = SearchDocument(doc)

    def lookup(self, query: str, strategy: str = "cascade") -> dict:
        """Run a named strategy against this index. No enrichment.

        Returns a posting set: dict[(doc, line), entry_dict].

        Strategies: direct, stemmed, ngram, cascade (default), merge.
        """
        from .strategy import STRATEGIES

        fn = STRATEGIES.get(strategy)
        if fn is None:
            raise ValueError(f"Unknown strategy: {strategy!r}. Available: {list(STRATEGIES)}")
        return fn(self, query)

    def search(self, query: str, strategy: str = "cascade") -> dict:
        """Lookup + enrich with quote provenance.

        Returns a posting set with callers and overlap filled in.
        """
        return self.enrich(self.lookup(query, strategy))

    # ── Quote provenance enrichment ──

    def _build_quote_index(self) -> dict[str, list[tuple[int, int, str]]]:
        """Build per-doc sorted quote ranges from DocumentIndex._quote_ranges.

        Cached — invalidated on refresh().
        """
        if self._quote_by_doc is not None:
            return self._quote_by_doc

        by_doc: dict[str, list[tuple[int, int, str]]] = {}
        for doc_name, start, end, caller in self._doc_index._quote_ranges:
            by_doc.setdefault(doc_name, []).append((start, end, caller))

        # Sort by start position for binary search; cache start lists
        starts: dict[str, list[int]] = {}
        for doc_name, ranges in by_doc.items():
            ranges.sort()
            starts[doc_name] = [r[0] for r in ranges]

        self._quote_by_doc = by_doc
        self._quote_starts = starts
        return self._quote_by_doc

    def enrich(self, posting: dict) -> dict:
        """Attach quote provenance (callers + overlap) to a posting set.

        For each (doc, line) entry, maps the line to its char range,
        finds overlapping quote ranges, and fills callers/total_callers.

        Returns the same posting dict, mutated in place.
        """
        from bisect import bisect_right

        quote_index = self._build_quote_index()

        for (doc_name, line_num), entry in posting.items():
            sdoc = self.documents.get(doc_name)
            if sdoc is None:
                continue

            # line_ranges is 0-indexed, lines are 1-based
            idx = line_num - 1
            if idx < 0 or idx >= len(sdoc.line_ranges):
                continue

            line_start, line_end = sdoc.line_ranges[idx]
            ranges = quote_index.get(doc_name)
            if not ranges:
                continue

            # Binary search: find first range that could overlap.
            # Ranges sorted by start. We want ranges where start <= line_end.
            doc_starts = self._quote_starts.get(doc_name, [])
            hi = bisect_right(doc_starts, line_end)

            callers = []
            for i in range(hi):
                r_start, r_end, caller = ranges[i]
                # Range must overlap the line
                if r_end < line_start:
                    continue
                # Overlap ratio: fraction of line covered by quote
                overlap_start = max(line_start, r_start)
                overlap_end = min(line_end, r_end)
                line_len = line_end - line_start + 1
                overlap_ratio = (overlap_end - overlap_start + 1) / line_len if line_len > 0 else 0
                if overlap_ratio > 0:
                    callers.append({"name": caller, "overlap": round(overlap_ratio, 3)})

            # Sort by overlap descending
            callers.sort(key=lambda c: -c["overlap"])
            entry["callers"] = callers
            entry["total_callers"] = len(callers)

        return posting

    def refresh(self):
        """Sync with underlying DocumentIndex — add new, remove stale."""
        current = set(self._doc_index.documents)
        cached = set(self.documents)

        # Invalidate quote caches
        self._quote_by_doc = None
        self._quote_starts = None

        # Remove stale
        for name in cached - current:
            del self.documents[name]

        # Add new
        for name in current - cached:
            self.documents[name] = SearchDocument(self._doc_index.documents[name])
