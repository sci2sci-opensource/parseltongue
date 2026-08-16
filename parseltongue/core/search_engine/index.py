"""DocumentSearchIndex — search-level index wrapping DocumentIndex.

Creates a SearchDocument per IndexedDocument, providing line-level
word, stem, and n-gram indices on top of the existing character-level
inverted index.

This is the entry point for the strategy cascade and the (strategy ...)
operator in the search system.

Concurrency: all query-visible state lives in a single ``_Snapshot``
object. Writers build a complete new snapshot, then swap one reference.
Readers grab ``self._snap`` once per query and work off that consistent
view — no locks, no races.
"""

from __future__ import annotations

import logging
import re as _re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .annotators import DEFAULT_ANNOTATORS, AnnotationStrategy
from .document import SearchDocument

log = logging.getLogger("parseltongue.search_index")

if TYPE_CHECKING:
    from parseltongue.core.quote_verifier.index import DocumentIndex

    from .synonyms import SynonymIndex


@dataclass(slots=True)
class _Snapshot:
    """Immutable query-time state — one reference swap replaces everything."""

    documents: dict[str, SearchDocument] = field(default_factory=dict)
    corpus_words: dict[str, dict[str, set[int]]] = field(default_factory=dict)
    corpus_stems: dict[str, dict[str, set[int]]] = field(default_factory=dict)
    stem_df: dict[str, int] = field(default_factory=dict)
    name_stems: dict[str, set[str]] = field(default_factory=dict)
    doc_lengths: dict[str, int] = field(default_factory=dict)
    avgdl: float = 1.0


def _build_snapshot(
    docs: dict[str, SearchDocument],
    synonyms: "SynonymIndex",
) -> _Snapshot:
    """Build a complete snapshot from a set of SearchDocuments."""
    from .stemmer import stem as _stem
    from .synonyms import ExpansionScope

    corpus_words: dict[str, dict[str, set[int]]] = {}
    corpus_stems: dict[str, dict[str, set[int]]] = {}
    df: dict[str, int] = {}
    name_stems: dict[str, set[str]] = {}

    for doc_name, sdoc in docs.items():
        for word, lines in sdoc.word_to_lines.items():
            if word not in corpus_words:
                corpus_words[word] = {}
            corpus_words[word][doc_name] = lines

        for s, lines in sdoc.stem_to_lines.items():
            if s not in corpus_stems:
                corpus_stems[s] = {}
            corpus_stems[s][doc_name] = lines

            for syn_entry in synonyms.expand(s, scope=ExpansionScope.DOCUMENTS):
                syn_stem = _stem(syn_entry.term)
                if syn_stem == s:
                    continue
                if syn_stem not in corpus_stems:
                    corpus_stems[syn_stem] = {}
                if doc_name not in corpus_stems[syn_stem]:
                    corpus_stems[syn_stem][doc_name] = set(lines)
                else:
                    corpus_stems[syn_stem][doc_name] |= lines

        ns = {_stem(t) for t in _re.split(r"[.\-_/: ]+", doc_name.lower()) if t}
        name_stems[doc_name] = ns

    doc_lengths: dict[str, int] = {}
    for doc_name, sdoc in docs.items():
        doc_lengths[doc_name] = sum(len(lines) for lines in sdoc.word_to_lines.values())
        seen = set(sdoc.stem_to_lines.keys()) | name_stems[doc_name]
        for s in seen:
            df[s] = df.get(s, 0) + 1

    N = len(docs)
    total = sum(doc_lengths.values())
    avgdl = total / N if N else 1.0
    if avgdl == 0:
        avgdl = 1.0

    return _Snapshot(
        documents=docs,
        corpus_words=corpus_words,
        corpus_stems=corpus_stems,
        stem_df=df,
        name_stems=name_stems,
        doc_lengths=doc_lengths,
        avgdl=avgdl,
    )


class DocumentSearchIndex:
    """Search-level index over a DocumentIndex.

    Wraps each IndexedDocument in a SearchDocument (line-level indices)
    and exposes the strategy dispatch for queries.

    All query state lives in ``self._snap`` (a ``_Snapshot``). Writers
    build a new snapshot and swap the reference atomically. Readers
    access ``self._snap`` once and use that view for the entire query.
    """

    __slots__ = (
        "_doc_index",
        "_snap",
        "_annotators",
        "_synonyms",
        "_quote_ranges",
        "_verifier_documents",
        "_line_callers_cache",
        "_line_callers_qr_id",
    )

    def __init__(
        self,
        doc_index: "DocumentIndex",
        annotators: list[AnnotationStrategy] | None = None,
        synonyms: "SynonymIndex | None" = None,
    ):
        from .synonyms import DEFAULT_SYNONYMS

        self._doc_index = doc_index
        self._annotators = annotators if annotators is not None else list(DEFAULT_ANNOTATORS)
        self._synonyms: SynonymIndex = synonyms if synonyms is not None else DEFAULT_SYNONYMS
        self._snap = _Snapshot()  # empty until _build
        # Pick up quote_ranges from backing index if present
        qr = getattr(doc_index, "_quote_ranges", [])
        self._quote_ranges: list = qr
        self._verifier_documents: dict = doc_index.documents if qr else {}
        self._line_callers_cache: dict[tuple[str, int], set[str]] | None = None
        self._line_callers_qr_id: int = -1
        self._build()

    # ── Snapshot accessors (back-compat for code that reads these directly) ──

    @property
    def documents(self) -> dict[str, SearchDocument]:
        return self._snap.documents

    @documents.setter
    def documents(self, value: dict[str, SearchDocument]):
        # Legacy setter — only used by _build; after COW this path is dead.
        self._snap.documents = value

    @property
    def _corpus_words(self) -> dict[str, dict[str, set[int]]]:
        return self._snap.corpus_words

    @property
    def _corpus_stems(self) -> dict[str, dict[str, set[int]]]:
        return self._snap.corpus_stems

    @property
    def _stem_df(self) -> dict[str, int]:
        return self._snap.stem_df

    @property
    def _name_stems(self) -> dict[str, set[str]]:
        return self._snap.name_stems

    # ── Quote provenance ──

    def set_quote_ranges(self, quote_ranges: list, verifier_documents: dict | None = None):
        """Set quote ranges for provenance enrichment. Invalidates caller cache.

        verifier_documents: the verifier's DocumentIndex.documents dict,
        needed because quote_ranges reference verifier doc names which may
        differ from file-indexed names in the snapshot.
        """
        self._quote_ranges = quote_ranges
        self._verifier_documents = verifier_documents or {}
        self._line_callers_cache = None
        self._line_callers_qr_id = -1
        log.debug("set_quote_ranges: %d ranges, %d verifier docs", len(quote_ranges), len(self._verifier_documents))

    # ── Build / refresh ──

    def _build(self):
        """Initial build — create SearchDocuments and snapshot."""
        log.debug("build: %d docs", len(self._doc_index.documents))
        docs: dict[str, SearchDocument] = {}
        for name, doc in self._doc_index.documents.items():
            sdoc = SearchDocument(doc)
            for ann in self._annotators:
                ann.annotate(sdoc)
            docs[name] = sdoc
        self._snap = _build_snapshot(docs, self._synonyms)

    def _rebuild_corpus(self):
        """Rebuild corpus from current documents — full snapshot swap."""
        self._snap = _build_snapshot(self._snap.documents, self._synonyms)

    # Back-compat alias
    _rebuild_df = _rebuild_corpus

    def refresh(self, doc_index: "DocumentIndex | None" = None):
        """Merge new/updated docs from doc_index into the snapshot.

        Merge-only: never removes docs from the snapshot. The snapshot
        accumulates docs from multiple sources (file indexer, verifier,
        cache restore). Only the file indexer's explicit delete path
        should remove docs — via remove_docs().
        """
        if doc_index is not None:
            self._doc_index = doc_index

        snap = self._snap  # read once

        # Find docs in doc_index that are new or changed vs snapshot
        added_or_updated: list[str] = []
        for name, doc in self._doc_index.documents.items():
            existing = snap.documents.get(name)
            if existing is None or existing._content_hash != doc.content_hash:
                added_or_updated.append(name)

        if not added_or_updated:
            return

        log.info(
            "refresh: merging %d into %d existing, doc_index has %d",
            len(added_or_updated),
            len(snap.documents),
            len(self._doc_index.documents),
        )

        # Start from current snapshot docs, add/update from doc_index
        new_docs = dict(snap.documents)
        for name in added_or_updated:
            sdoc = SearchDocument(self._doc_index.documents[name])
            for ann in self._annotators:
                ann.annotate(sdoc)
            new_docs[name] = sdoc

        # Single reference swap — atomic under CPython GIL.
        self._snap = _build_snapshot(new_docs, self._synonyms)

    def remove_docs(self, names: set[str]):
        """Explicitly remove docs from the snapshot (e.g. file indexer detected deletion)."""
        snap = self._snap
        remaining = {n: s for n, s in snap.documents.items() if n not in names}
        if len(remaining) < len(snap.documents):
            log.info("remove_docs: %d → %d docs", len(snap.documents), len(remaining))
            self._snap = _build_snapshot(remaining, self._synonyms)

    # ── Query ──

    def match_docs(self, predicate) -> dict:
        """Return doc-level postings (line 0) for documents matching predicate."""
        import os.path

        snap = self._snap
        result = {}
        for name in snap.documents:
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

        stemmed=True  → uses corpus_stems (includes synonym expansions)
        stemmed=False → uses corpus_words (exact normalized match)

        Returns a posting set. Replaces per-doc scanning in strategies.
        """
        from .stemmer import stem as _stem
        from .strategy import _make_posting

        snap = self._snap
        corpus = snap.corpus_stems if stemmed else snap.corpus_words

        if not tokens:
            return {}

        def _get(token: str) -> dict[str, set[int]]:
            key = _stem(token) if stemmed else token
            return corpus.get(key, {})

        per_token = [_get(t) for t in tokens]

        doc_sets = [set(p.keys()) for p in per_token]
        common_docs = doc_sets[0]
        for ds in doc_sets[1:]:
            common_docs &= ds
            if not common_docs:
                return {}

        result: dict = {}
        for doc_name in common_docs:
            sdoc = snap.documents.get(doc_name)
            if sdoc is None:
                continue
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

    def _build_line_callers(self) -> dict[tuple[str, int], set[str]]:
        """Build (doc_name, line_num) → {callers} from quote_ranges.

        Quote ranges use verifier doc names (arbitrary, e.g. "engine.py")
        while postings use file-indexed paths (e.g. "parseltongue/core/engine.py").
        We match by content hash to map verifier→file-indexed names, use verifier
        docs for char→line conversion, and emit result keys under file-indexed
        names so they match posting keys.
        """
        quote_ranges = self._quote_ranges
        vdocs = self._verifier_documents
        if not quote_ranges or not vdocs:
            return {}

        # Content hash → file-indexed name(s) for matching
        snap_docs = self._snap.documents
        import hashlib

        hash_to_snap: dict[str, list[str]] = {}
        for snap_name, sdoc in snap_docs.items():
            h = hashlib.sha256(sdoc.lines[0].encode() if sdoc.lines else b"").hexdigest()[:16]
            # Use full text hash via the line content
            full = "\n".join(sdoc.lines)
            h = hashlib.sha256(full.encode()).hexdigest()[:16]
            hash_to_snap.setdefault(h, []).append(snap_name)

        # Verifier name → file-indexed name(s)
        vname_to_snap: dict[str, list[str]] = {}
        for vname, vdoc in vdocs.items():
            h = hashlib.sha256(vdoc.original_text.encode()).hexdigest()[:16]
            vname_to_snap[vname] = hash_to_snap.get(h, [vname])

        # Group ranges by doc
        by_doc: dict[str, list[tuple[int, int, str]]] = {}
        for doc_name, start, end, caller in quote_ranges:
            if start < 0:
                continue
            by_doc.setdefault(doc_name, []).append((start, end, caller))

        result: dict[tuple[str, int], set[str]] = {}

        for vname, ranges in by_doc.items():
            vdoc = vdocs.get(vname)
            if vdoc is None:
                continue
            text = vdoc.original_text
            snap_names = vname_to_snap.get(vname, [vname])

            # Build newline index for char→line
            newlines = [-1]
            for i, ch in enumerate(text):
                if ch == "\n":
                    newlines.append(i)

            def _char_to_line(pos: int, _nl=newlines) -> int:
                lo, hi = 0, len(_nl) - 1
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if _nl[mid] < pos:
                        lo = mid
                    else:
                        hi = mid - 1
                return lo + 1

            for start, end, caller in ranges:
                start_line = _char_to_line(start)
                end_line = _char_to_line(end)
                for line in range(start_line, end_line + 1):
                    for name in snap_names:
                        key = (name, line)
                        if key not in result:
                            result[key] = set()
                        result[key].add(caller)

        log.debug("_build_line_callers: %d ranges, %d vdocs → %d entries", len(quote_ranges), len(by_doc), len(result))
        return result

    def enrich(self, posting: dict) -> dict:
        """Attach quote provenance (callers) to a posting set.

        Uses cached line→callers index instead of per-hit trace() calls.
        O(1) per posting entry instead of O(docs × ranges).
        Cache invalidates when _quote_ranges identity changes.
        """
        qr = self._quote_ranges
        if not qr:
            log.debug("enrich: no quote_ranges (%d snap docs)", len(self._snap.documents))
            return posting

        # Cache line_callers — rebuild only when quote_ranges changes
        qr_id = id(qr)
        if self._line_callers_cache is None or self._line_callers_qr_id != qr_id:
            self._line_callers_cache = self._build_line_callers()
            self._line_callers_qr_id = qr_id
            log.debug(
                "enrich: rebuilt line_callers from %d quote_ranges → %d entries", len(qr), len(self._line_callers_cache)
            )

        line_callers = self._line_callers_cache
        if not line_callers:
            return posting

        matched = 0
        for (doc_name, line_num), entry in posting.items():
            callers_set = line_callers.get((doc_name, line_num))
            if not callers_set:
                continue
            matched += 1
            callers = [{"name": c, "overlap": 1.0} for c in callers_set]
            callers.sort(key=lambda c: str(c["name"]))
            entry["callers"] = callers
            entry["total_callers"] = len(callers)

        log.debug("enrich: %d/%d postings matched callers", matched, len(posting))
        return posting
