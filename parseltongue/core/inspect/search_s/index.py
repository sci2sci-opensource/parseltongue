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

    __slots__ = ("_doc_index", "documents", "_annotators")

    def __init__(
        self,
        doc_index: "DocumentIndex",
        annotators: list[AnnotationStrategy] | None = None,
    ):
        self._doc_index = doc_index
        self.documents: dict[str, SearchDocument] = {}
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

    def enrich(self, posting: dict) -> dict:
        """Attach quote provenance (callers + overlap) to a posting set.

        Delegates to DocumentIndex.trace() which matches text and returns
        overlapping quotes with callers. Returns the same posting dict,
        mutated in place.
        """
        log.info(
            "enrich: _doc_index id=%s, docs=%d, quote_ranges=%d, posting=%d entries",
            id(self._doc_index), len(self._doc_index.documents),
            len(self._doc_index._quote_ranges), len(posting),
        )
        if not self._doc_index._quote_ranges:
            return posting

        for (_doc_name, _line_num), entry in posting.items():
            context = entry.get("context", "")
            if not context or not context.strip():
                continue

            hits = self._doc_index.trace(context.strip(), max_results=50)
            if not hits:
                continue

            best: dict[str, float] = {}
            for hit in hits:
                c, o = hit["caller"], hit["overlap"]
                if c not in best or o > best[c]:
                    best[c] = o

            callers = [{"name": c, "overlap": round(o, 3)} for c, o in best.items()]
            callers.sort(key=lambda c: -c["overlap"])
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

        new_names = {n for n, _ in new_set}
        old_names = {n for n, _ in old_set}
        new_h = dict(new_set)
        old_h = dict(old_set)

        removed = old_names - new_names
        added = new_names - old_names
        updated = {n for n in new_names & old_names if new_h[n] != old_h[n]}

        log.debug("refresh: +%d -%d ~%d docs", len(added), len(removed), len(updated))

        # Build new dict atomically — avoids concurrent modification during iteration
        new_docs = {n: s for n, s in self.documents.items() if n not in removed}
        for name in added | updated:
            sdoc = SearchDocument(self._doc_index.documents[name])
            for ann in self._annotators:
                ann.annotate(sdoc)
            new_docs[name] = sdoc
        self.documents = new_docs
