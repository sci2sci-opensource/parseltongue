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

    from .synonyms import SynonymIndex


class DocumentSearchIndex:
    """Search-level index over a DocumentIndex.

    Wraps each IndexedDocument in a SearchDocument (line-level indices)
    and exposes the strategy dispatch for queries.
    """

    __slots__ = (
        "_doc_index",
        "documents",
        "_annotators",
        "_synonyms",
        "_stem_df",
        "_name_stems",
        "_corpus_stems",
        "_corpus_words",
    )

    def __init__(
        self,
        doc_index: "DocumentIndex",
        annotators: list[AnnotationStrategy] | None = None,
        synonyms: "SynonymIndex | None" = None,
    ):
        from .synonyms import DEFAULT_SYNONYMS

        self._doc_index = doc_index
        self.documents: dict[str, SearchDocument] = {}
        self._annotators = annotators if annotators is not None else list(DEFAULT_ANNOTATORS)
        self._synonyms: SynonymIndex = synonyms if synonyms is not None else DEFAULT_SYNONYMS
        self._stem_df: dict[str, int] = {}
        self._name_stems: dict[str, set[str]] = {}
        # Corpus-level inverted indices — synonyms baked in at build time.
        # stem → {doc_name → set[line_num]}, word → {doc_name → set[line_num]}
        self._corpus_stems: dict[str, dict[str, set[int]]] = {}
        self._corpus_words: dict[str, dict[str, set[int]]] = {}
        self._build()

    def _build(self):
        """Create SearchDocument wrappers and run annotators."""
        log.debug("build: %d docs", len(self._doc_index.documents))
        for name, doc in self._doc_index.documents.items():
            sdoc = SearchDocument(doc)
            for ann in self._annotators:
                ann.annotate(sdoc)
            self.documents[name] = sdoc
        self._rebuild_df()

    def _rebuild_corpus(self):
        """Rebuild corpus-level inverted indices with synonyms baked in.

        Builds three things at index time (not per-query):
        1. _corpus_words: word → {doc → lines} — exact normalized words
        2. _corpus_stems: stem → {doc → lines} — stemmed, WITH synonym
           expansions injected so expanded search is a plain lookup
        3. _stem_df / _name_stems — document frequency for BM25

        Synonym injection: for each stem in each doc, expand via
        DEFAULT_SYNONYMS (DOCUMENTS + UNIVERSAL scope), insert all
        synonym stems pointing at the same doc/lines. Query-time
        expansion becomes unnecessary — just look up the query stem.
        """
        import re

        from .stemmer import stem as _stem
        from .synonyms import ExpansionScope

        corpus_words: dict[str, dict[str, set[int]]] = {}
        corpus_stems: dict[str, dict[str, set[int]]] = {}
        df: dict[str, int] = {}
        name_stems: dict[str, set[str]] = {}

        for doc_name, sdoc in self.documents.items():
            # Word index → corpus
            for word, lines in sdoc.word_to_lines.items():
                if word not in corpus_words:
                    corpus_words[word] = {}
                corpus_words[word][doc_name] = lines

            # Stem index → corpus + synonym injection
            for s, lines in sdoc.stem_to_lines.items():
                # Original stem
                if s not in corpus_stems:
                    corpus_stems[s] = {}
                corpus_stems[s][doc_name] = lines

                # Inject synonyms: if "error" is in this doc, also index
                # under "exception", "raise", etc. so query for those
                # hits this doc/lines without per-query expansion.
                for syn_entry in self._synonyms.expand(s, scope=ExpansionScope.DOCUMENTS):
                    syn_stem = _stem(syn_entry.term)
                    if syn_stem == s:
                        continue
                    if syn_stem not in corpus_stems:
                        corpus_stems[syn_stem] = {}
                    if doc_name not in corpus_stems[syn_stem]:
                        corpus_stems[syn_stem][doc_name] = set(lines)
                    else:
                        corpus_stems[syn_stem][doc_name] |= lines

            # Name stems for BM25
            ns = {_stem(t) for t in re.split(r"[.\-_/: ]+", doc_name.lower()) if t}
            name_stems[doc_name] = ns

        # df: count docs per stem (content + name)
        for doc_name, sdoc in self.documents.items():
            seen = set(sdoc.stem_to_lines.keys()) | name_stems[doc_name]
            for s in seen:
                df[s] = df.get(s, 0) + 1

        self._corpus_words = corpus_words
        self._corpus_stems = corpus_stems
        self._stem_df = df
        self._name_stems = name_stems

    # Back-compat alias
    _rebuild_df = _rebuild_corpus

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

    def corpus_lookup(self, tokens: tuple[str, ...] | list[str], *, stemmed: bool = True) -> dict:
        """Fast corpus-level lookup — pure dict + set intersection.

        stemmed=True  → uses _corpus_stems (includes synonym expansions)
        stemmed=False → uses _corpus_words (exact normalized match)

        Returns a posting set. Replaces per-doc scanning in strategies.
        """
        from .stemmer import stem as _stem
        from .strategy import _make_posting

        corpus = self._corpus_stems if stemmed else self._corpus_words

        if not tokens:
            return {}

        # For each token, collect {doc → lines} from corpus index
        def _get(token: str) -> dict[str, set[int]]:
            key = _stem(token) if stemmed else token
            return corpus.get(key, {})

        # Intersect across tokens: only docs (and lines) that have ALL tokens
        per_token = [_get(t) for t in tokens]

        # Find docs present in all token posting lists
        doc_sets = [set(p.keys()) for p in per_token]
        common_docs = doc_sets[0]
        for ds in doc_sets[1:]:
            common_docs &= ds
            if not common_docs:
                return {}

        result: dict = {}
        for doc_name in common_docs:
            sdoc = self.documents.get(doc_name)
            if sdoc is None:
                continue
            # Intersect line sets across tokens within this doc
            line_sets = [p[doc_name] for p in per_token]
            common_lines = line_sets[0]
            for ls in line_sets[1:]:
                common_lines = common_lines & ls
            for line_num in common_lines:
                if line_num <= len(sdoc.lines):
                    result[(doc_name, line_num)] = _make_posting(doc_name, line_num, sdoc.lines)

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
        return fn(self, query)

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
            id(self._doc_index),
            len(self._doc_index.documents),
            len(self._doc_index._quote_ranges),
            len(posting),
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
        self._rebuild_df()
