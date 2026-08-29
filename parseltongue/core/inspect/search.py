"""Search — full-text search across loaded documents with pltg provenance tracing.

Supports pltg S-expression queries over the inverted index::

    Set operators (work on posting sets internally):

    "raise ValueError"                          — literal phrase lookup
    (and "def derive" "using")                  — intersection (same line must match both)
    (or "raise ValueError" "raise Syntax")      — union of posting sets
    (not "raise" "test")                        — difference (first minus second)
    (in "engine.py" "raise")                    — restrict to document (exact, suffix, or glob)
    (near 3 "raise" "ValueError")               — proximity within N lines
    (seq "def derive" "raise")                  — a before b in same document
    (re "raise (ValueError|NameError)")         — regex over all indexed lines
    (lines 400 500 (in "engine.py" (re ".")))   — restrict to line range

    Context expansion (add surrounding lines to matches):

    (context 3 "raise")                         — N lines before and after each match
    (before 3 "raise")                          — N lines before each match only
    (after 3 "raise")                           — N lines after each match only

    Ranking:

    (rank "callers" query)                      — rank by caller count + overlap
    (rank "coverage" query)                     — rank by overlap + caller count
    (rank "document" query)                     — group by doc, most-traced first
    (rank "line" query)                         — sort by document then line

    Output:

    (count query)                               — integer count of matches
    (results query)                             — convert posting set to sr forms
    (limit N query)                             — take first N entries

    Composition:

    (scope name expr)                           — evaluate expr in a registered scope

Search results as pltg data::

    (sr "engine.py" 10 1 "def derive(self):" (("engine.derive" 0.85)))

Accessors: ``sr-doc``, ``sr-line``, ``sr-column``, ``sr-context``, ``sr-callers``.

Queries starting with ``(`` are parsed as S-expressions and evaluated
by a SearchSystem whose operators work on posting sets.
Plain strings are literal phrase lookups (backwards compatible).

Scopes: external Systems registered via ``register_scope(name, system)``
define a defterm in the SearchSystem. ``(scope name expr)`` evaluates
``expr`` in that System.  ``unregister_scope(name)`` retracts the term.
"""

from __future__ import annotations

import gc
import logging
import threading
from typing import Callable

from .store import SearchStore
from .systems.bench_system import BenchSubsystem
from .systems.search_system_2 import SearchSystem2 as SearchSystem

log = logging.getLogger("parseltongue.search")


class Search:
    """View layer over SearchSystem.

    ``evaluate(expr)`` — raw pltg result from the search system.
    ``query(text)`` — formatted display structure with ranking and pagination.

    All logic (set ops, ranking, limiting) lives in SearchSystem as pltg
    operators. Search just formats the output.
    """

    def __init__(self, store: SearchStore):
        # _loaded flips to True at the end of __init__ so callers (e.g. the
        # refresh loop) can detect a half-built Search — the cache read may
        # take minutes on large corpora and a stray reindex during that
        # window would thrash the loader.
        self._loaded = False
        # Serializes all index mutation (background refresh loop, client
        # `pg reindex` / `pg index` threads) within the daemon process.
        self._reindex_lock = threading.Lock()
        self._save_dirty = False
        self._index = store.load_index()
        self._store = store
        # Try to restore cached search index (stems, phrases, meta, corpus)
        cached_search = store.load_search_index(self._index)
        if cached_search is not None:
            self._system = SearchSystem(cached_search, self._collect)
        else:
            self._system = SearchSystem(self._index, self._collect)
        # The corpus is now the bulk of the heap and it is long-lived. Move
        # it to the permanent generation so the cyclic collector stops
        # re-walking it on every gen-2 pass for the daemon's lifetime.
        gc.freeze()
        self._loaded = True

    def is_loaded(self) -> bool:
        """True once the cached index has been fully deserialized."""
        return self._loaded

    # ── Legacy (v1) cache decision ──

    @property
    def legacy_cache(self):
        """The untouched v1 cache found at load, or None."""
        return self._store.legacy

    def notices(self) -> list[str]:
        """Operator-facing state worth announcing at contact time: a v1
        cache awaiting a decision, a search index built by another
        tokenizer version. Empty when there is nothing to say."""
        out: list[str] = []
        if self._store.legacy is not None:
            out.extend(self._store.legacy.describe())
        built = getattr(self._store, "tokenizer_built_with", None)
        if built is not None:
            from parseltongue.core.search_engine.document import TOKENIZER_VERSION

            out.append(
                f"search index: built with tokenizer v{built}, this version is v{TOKENIZER_VERSION} — "
                "queries for path segments / camelCase parts miss until `pg reindex --force`"
            )
        return out

    def cache_choice(self, choice: str, on_progress=None) -> str:
        """Apply the operator's decision about a v1 cache. Returns a summary.

        The v1 cache is already loaded and served (streamed at start). The
        choice is about the files on disk:

        convert — move the v1 files aside as *.v1.pgz and write the loaded
                  corpus in the current layout. No re-walk.
        migrate — convert, then delete the v1 files.
        rebuild — move the v1 files aside as *.v1.pgz and re-walk the
                  recorded directory with this version.
        keep    — leave everything exactly as it is; every start streams
                  the v1 files again and saves stay held.
        """
        from .legacy import discard, set_aside

        legacy = self._store.legacy
        if legacy is None:
            if choice == "migrate":
                # After a convert/rebuild the v1 files live on as *.v1.pgz
                # backups; migrate is the operator's explicit call to remove them.
                backups = self._store._store.legacy_backups(self._store._path) if self._store._store else []
                if not backups:
                    return "No legacy cache pending and no *.v1.pgz backups to remove."
                for p in backups:
                    p.unlink()
                return "Migrated: removed " + ", ".join(p.name for p in backups)
            return "No legacy cache pending."
        if choice == "keep":
            return "Kept: v1 files left untouched; loaded in place, cache saves held."
        if choice not in ("convert", "migrate", "rebuild"):
            return f"Unknown choice {choice!r}: expected convert | migrate | rebuild | keep."
        with self._reindex_lock:
            # Set aside first: the current layout is written under the same
            # names, so the v1 files are never overwritten, only renamed.
            moved = set_aside(legacy)
            self._store.legacy = None
        directory = legacy.directory or next(iter(self._store._indexed_dirs), ".")
        if choice == "rebuild":
            # index_dir takes the reindex lock itself.
            count = self.index_dir(directory, on_progress=on_progress, force=True)
            with self._reindex_lock:
                self._store.flush_pending_save()
                self._store.save_search_index(self._system._search_index)
            return f"Rebuilt: {count} files re-read from {directory}; v1 files kept as " + ", ".join(
                p.name for p in moved
            )
        with self._reindex_lock:
            # convert / migrate: persist what is loaded, in the current layout.
            self._store._pending_save = self._store._pending_save or {
                "directory": directory,
                "file_hashes": self._store._dir_hashes.get(self._store._path, {}),
                "index": self._index,
                "changed_texts": {},
                "deleted_keys": set(),
            }
            self._store.flush_pending_save()
            self._store.save_search_index(self._system._search_index)
            n = len(self._index.documents)
            if choice == "migrate":
                # Only after the new files exist: remove the set-aside v1 copies.
                from .legacy import LegacyCache

                gone = discard(
                    LegacyCache(
                        key=legacy.key,
                        idx_path=moved[0] if moved else None,
                        six_path=moved[1] if len(moved) > 1 else None,
                    )
                )
                return f"Migrated: {n} documents saved in the current layout; deleted " + ", ".join(
                    p.name for p in gone
                )
            return f"Converted: {n} documents saved in the current layout; v1 files kept as " + ", ".join(
                p.name for p in moved
            )

    def corpus_root(self) -> str:
        """Stable fingerprint of the indexed corpus — for cache keys.

        Hashes the per-file content hashes the store already tracks, so
        anything whose result depends on the corpus (screen verdicts for
        absence/obligation claims) can key on corpus state, not just the
        .pltg Merkle root. Empty string when nothing is indexed.
        """
        import hashlib

        entries = []
        for dir_hashes in (getattr(self._store, "_dir_hashes", None) or {}).values():
            entries.extend(dir_hashes.items())
        if not entries:
            return ""
        h = hashlib.sha256()
        for rel, digest in sorted(entries):
            h.update(rel.encode())
            h.update(digest.encode())
        return h.hexdigest()[:16]

    def reindex_busy(self) -> bool:
        """True while a reindex/index pass holds the lock (advisory — for
        pollers that would rather skip a tick than queue behind a pass)."""
        return self._reindex_lock.locked()

    def register_scope(self, name: str, system: BenchSubsystem):
        """Register a BenchSubsystem as a named scope."""
        self._system.register_scope(name, system)

    def unregister_scope(self, name: str):
        """Unregister a named scope."""
        self._system.unregister_scope(name)

    def add(self, name: str, text: str) -> None:
        """Add a document and refresh the search index."""
        if name not in self._index.documents:
            self._index.add(name, text)

    def refresh(self, doc_index=None) -> None:
        """Sync search system with backing DocumentIndex.

        If *doc_index* is provided, merges its documents and quote ranges
        into the existing index (e.g. the verifier's DocumentIndex carries
        quote ranges for provenance tracing). Does NOT replace the index —
        directory-indexed files are preserved.
        """
        if doc_index is not None:
            # Merge verifier docs into existing index (adds quote ranges)
            for name, doc in doc_index.documents.items():
                if name not in self._index.documents:
                    self._index.add(name, doc.original_text)
            # Import quote ranges + verifier docs for provenance enrichment
            self._system._search_index.set_quote_ranges(doc_index._quote_ranges, doc_index.documents)
        self._system.refresh()

    def _sync(self, updated_index, deleted: set[str] | None = None):
        """Sync all references after _update_index may have replaced DocumentIndex."""
        if updated_index is not self._index:
            self._index = updated_index
            self._system._index = updated_index
        if deleted:
            self._system._search_index.remove_docs(deleted)
        self._system.refresh()

    def index_dir(
        self,
        directory: str,
        extensions: list[str] | None = None,
        exclude: list[str] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        force: bool = False,
    ) -> int:
        with self._reindex_lock:
            updated, count, deleted = self._store.index_incremental(
                self._index,
                directory,
                extensions,
                exclude,
                on_progress,
                force=force,
            )
            # Sync first — changes become searchable before the (slow) disk
            # writes below run.
            self._sync(updated, deleted)
            if count > 0:
                self._save_dirty = True
            self._flush_saves_locked()
            return count

    def reindex(
        self,
        on_progress: Callable[[int, int, str], None] | None = None,
        force: bool = False,
        defer_save: bool = False,
    ) -> int:
        """Re-walk tracked directories, picking up new/changed/deleted files.

        Walks all previously indexed directories to discover new files,
        re-hashes existing files, and updates stale entries.

        force=True bypasses stat/hash caches — full tree walk + re-read.

        defer_save=True makes the pass memory-only: changes become
        searchable but the (slow, full-corpus) cache writes are queued
        until flush_saves(). The background refresh loop uses this to
        batch an editing burst into one save on the first quiet pass.

        No-ops with a warning if the cached index isn't fully loaded yet,
        so background refresh loops don't race the initial deserialize.
        """
        if not self._loaded:
            log.warning("Search.reindex: skipped — cached index not yet loaded.")
            return 0
        with self._reindex_lock:
            updated, count, deleted = self._store.reindex(self._index, on_progress, force=force)
            # Sync first — changes become searchable before the (slow) disk
            # writes below run.
            self._sync(updated, deleted)
            if force:
                # A forced pass re-reads files, but DocumentIndex.add keeps
                # documents whose content hash is unchanged — so the search
                # documents (tokenizer-dependent) must be rebuilt explicitly,
                # or `pg reindex --force` after a tokenizer bump changes nothing.
                self._rebuild_search_documents()
                self._save_dirty = True
            if count > 0:
                self._save_dirty = True
            if defer_save:
                return count
            self._flush_saves_locked()
            return count

    def _rebuild_search_documents(self) -> None:
        """Re-derive every SearchDocument from the DocumentIndex with the
        current tokenizer; clears the 'built with another tokenizer' notice."""
        self._system._search_index._build()
        self._store.tokenizer_built_with = None

    def flush_saves(self):
        """Write queued cache updates from defer_save passes to disk."""
        with self._reindex_lock:
            self._flush_saves_locked()

    def save_pending(self) -> bool:
        """True when defer_save passes have unflushed changes queued."""
        return self._save_dirty

    def _flush_saves_locked(self):
        self._store.flush_pending_save()
        if self._save_dirty:
            self._store.save_search_index(self._system._search_index)
            self._save_dirty = False

    def evaluate(self, expression: str):
        """Evaluate an S-expression in the search system, return raw result.

        Returns whatever pltg produces — posting set, sr list, int, etc.
        """
        return self._system.evaluate(expression)

    def query(
        self,
        text: str,
        max_lines: int = 20,
        max_callers: int = 5,
        offset: int = 0,
        rank: str = "callers",
    ) -> dict:
        """Search and format results for display.

        Evaluates the query, ranks, paginates, and returns::

            {
                "total_lines": int,
                "total_callers": int,
                "offset": int,
                "lines": [...]
            }

        Each line: {document, line, column, context, callers, total_callers}.
        """
        # All queries go through SearchSystem2 — RRF + BM25 pipeline
        result = self._system.evaluate(text.strip())
        posting = self._to_display_posting(result)

        # Context/before/after queries need line-order ranking to keep
        # surrounding lines grouped with their matches.
        import re as _re_mod

        if _re_mod.search(r"\(\s*(context|before|after)\b", text):
            rank = "line"

        # Rank via the search system operator
        from parseltongue.core.atoms import Symbol

        rank_fn = self._system._pltg_system.engine.env[Symbol("rank")]
        ranked = rank_fn(rank, posting)

        # Paginate; max_lines=0 means everything from offset on.
        all_values = list(ranked.values())
        page = all_values[offset : offset + max_lines] if max_lines else all_values[offset:]

        all_callers: set[str] = set()
        for ln in all_values:
            for c in ln.get("callers", []):
                all_callers.add(c["name"])

        return {
            "total_lines": len(all_values),
            "total_callers": len(all_callers),
            "offset": offset,
            "lines": page,
        }

    def _to_display_posting(self, result) -> dict:
        """Convert any search system result to a posting set for display.

        Uses the SearchSystem's posting_morphism to dispatch tagged forms
        (sr, ln, dx, hn) back to posting dicts by head symbol.
        """
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            return self._system.posting_morphism.inverse(result)
        if isinstance(result, (int, float)):
            return {
                ("__result__", 0): {
                    "document": "__result__",
                    "line": 0,
                    "column": 1,
                    "context": str(result),
                    "callers": [],
                    "total_callers": 0,
                }
            }
        return {}

    def _collect(self, text: str, max_lines: int, max_callers: int):
        """Collect all matching lines with their callers."""
        idx = self._index

        doc_hits = idx.search(text)
        traced = idx.trace(text)

        callers_by_line: dict[tuple[str, int], dict[str, dict]] = {}
        all_callers: set[str] = set()
        for r in traced:
            key = (r["document"], r["line"])
            name = r["caller"]
            all_callers.add(name)
            by_name = callers_by_line.setdefault(key, {})
            if name not in by_name or r["overlap"] > by_name[name]["overlap"]:
                by_name[name] = {"name": name, "overlap": r["overlap"]}

        seen: set[tuple[str, int]] = set()
        lines = []

        for r in traced:
            key = (r["document"], r["line"])
            if key in seen:
                continue
            seen.add(key)
            callers = sorted(callers_by_line[key].values(), key=lambda c: -c["overlap"])
            lines.append(
                {
                    "document": r["document"],
                    "line": r["line"],
                    "column": r.get("column", 1),
                    "context": r["context"],
                    "callers": callers,
                    "total_callers": len(callers),
                }
            )

        for hit in doc_hits:
            key = (hit["document"], hit["line"])
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                {
                    "document": hit["document"],
                    "line": hit["line"],
                    "column": hit.get("column", 1),
                    "context": hit["context"],
                    "callers": [],
                    "total_callers": 0,
                }
            )

        return lines, all_callers
