"""DocumentSearchIndex — search-level index wrapping DocumentIndex.

Creates a SearchDocument per IndexedDocument, providing line-level
word, stem, and n-gram indices on top of the existing character-level
inverted index.

This is the entry point for the strategy cascade and the (strategy ...)
operator in the search system.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .annotators import DEFAULT_ANNOTATORS, AnnotationStrategy
from .document import SearchDocument

log = logging.getLogger("parseltongue.search_index")

if TYPE_CHECKING:
    from parseltongue.core.quote_verifier.index import DocumentIndex


class DocumentSearchIndex:
    """Search-level index over a DocumentIndex.

    Wraps each IndexedDocument in a SearchDocument (line-level indices)
    and exposes the strategy dispatch for queries.
    """

    __slots__ = ("_doc_index", "documents", "_quote_by_doc", "_quote_starts", "_annotators")

    def __init__(
        self,
        doc_index: "DocumentIndex",
        annotators: list[AnnotationStrategy] | None = None,
    ):
        self._doc_index = doc_index
        self.documents: dict[str, SearchDocument] = {}
        self._quote_by_doc: dict[str, list[tuple[int, int, str]]] | None = None
        self._quote_starts: dict[str, list[int]] | None = None
        self._annotators = annotators if annotators is not None else list(DEFAULT_ANNOTATORS)
        self._build()

    def _build(self):
        """Create SearchDocument wrappers and run annotators."""
        log.debug("build: %d docs", len(self._doc_index.documents))
        for name, doc in self._doc_index.documents.items():
            sdoc = SearchDocument(doc)
            for ann in self._annotators:
                ann.annotate(sdoc)
            self.documents[name] = sdoc

    def match_docs(self, predicate) -> dict:
        """Return doc-level postings (line 0) for documents matching predicate.

        predicate: callable(doc_name) -> bool
        """
        import os.path

        result = {}
        for name in self.documents:
            if predicate(name):
                result[(name, 0)] = {
                    "document": name,
                    "line": 0,
                    "column": 0,
                    "context": os.path.basename(name),
                    "callers": [],
                    "total_callers": 0,
                }
        return result

    def lookup(self, query: str, strategy: str = "rrf") -> dict:
        """Run a named strategy against this index. No enrichment.

        Returns a posting set: dict[(doc, line), entry_dict].

        Strategies: direct, stemmed, ngram, expanded, meta, cascade, merge, rrf (default).
        """
        from .strategy import STRATEGIES

        fn = STRATEGIES.get(strategy)
        if fn is None:
            raise ValueError(f"Unknown strategy: {strategy!r}. Available: {list(STRATEGIES)}")
        return fn(self, query)  # type: ignore[operator]

    def search(self, query: str, strategy: str = "rrf") -> dict:
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
        assert self._quote_starts is not None

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
            callers.sort(key=lambda c: -c["overlap"])  # type: ignore[operator]
            entry["callers"] = callers
            entry["total_callers"] = len(callers)

        return posting

    def refresh(self, doc_index: "DocumentIndex | None" = None):
        """Sync with underlying DocumentIndex — add new, update stale, remove deleted.

        If *doc_index* is provided, replaces the backing DocumentIndex first
        (needed when Search.reindex creates a new DocumentIndex object).
        """
        if doc_index is not None:
            self._doc_index = doc_index

        new_set = {(n, d.content_hash) for n, d in self._doc_index.documents.items()}
        old_set = {(n, s._content_hash) for n, s in self.documents.items()}

        if new_set == old_set:
            return

        self._quote_by_doc = None
        self._quote_starts = None

        new_names = {n for n, _ in new_set}
        old_names = {n for n, _ in old_set}
        new_h = dict(new_set)
        old_h = dict(old_set)

        removed = old_names - new_names
        added = new_names - old_names
        updated = {n for n in new_names & old_names if new_h[n] != old_h[n]}

        log.debug("refresh: +%d -%d ~%d docs", len(added), len(removed), len(updated))

        for name in removed:
            del self.documents[name]

        for name in added | updated:
            sdoc = SearchDocument(self._doc_index.documents[name])
            for ann in self._annotators:
                ann.annotate(sdoc)
            self.documents[name] = sdoc
