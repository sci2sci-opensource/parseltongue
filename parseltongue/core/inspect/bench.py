"""Bench — workstation for observing .pltg samples.

Prepare a sample, then observe: ``lens()`` for structure,
``evaluate()`` for health. Backed by Merkle tree caching.

The Bench owns sample status and integrity labels. A Technician
handles loading (cold, cache hit, hot-patch, background reload)
and flips the labels via a private callback. A Store handles
all disk I/O.

Usage::

    from parseltongue.core.inspect.bench import Bench

    bench = Bench()
    bench.prepare("parseltongue/core/validation/core_clean.pltg")

    lens = bench.lens()          # structural observation
    dx   = bench.evaluate()      # consistency observation

    dx.summary()
    dx.focus("readme.").issues()
    dx.find("count")
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..loader.lazy_loader import LazyLoadResult
from .evaluation import Evaluation
from .optics import Lens
from .optics.hologram import Hologram
from .perspectives.md_debugger import MDebuggerPerspective
from .store import SearchStore, Store
from .technician import Sample, Technician

log = logging.getLogger("parseltongue.bench")


class Bench:
    """Workstation for .pltg samples.

    ``prepare(path)`` loads the file (cached via Merkle trees).
    ``lens()`` returns structural observation.
    ``evaluate()`` returns consistency observation.
    Both are first-class objects with focus, search, and filtering.
    """

    class Integrity:
        """Integrity state of a prepared sample.

        - verified:  full load completed, or hot-patch confirmed by background reload
        - unknown:   hot-patched but not yet verified by background reload
        - corrupted: change detected, not yet patched
        """

        VERIFIED = "verified"
        UNKNOWN = "unknown"
        CORRUPTED = "corrupted"

        def __init__(self):
            self._state: dict[str, str] = {}

        def __getitem__(self, path: str) -> str:
            return self._state.get(path, self.CORRUPTED)

        def __repr__(self) -> str:
            if not self._state:
                return "Integrity(empty)"
            parts = [f"{Path(p).name}: {s}" for p, s in self._state.items()]
            return f"Integrity({', '.join(parts)})"

    class Status:
        """Lifecycle status of a prepared sample.

        - initialized: bench created, no sample loaded yet
        - loading:     background reload in progress (hot-patched system available)
        - live:        full loader completed, fully operational
        """

        INITIALIZED = "initialized"
        LOADING = "loading"
        LIVE = "live"

        def __init__(self):
            self._state: dict[str, str] = {}

        def __getitem__(self, path: str) -> str:
            return self._state.get(path, self.INITIALIZED)

        def __repr__(self) -> str:
            if not self._state:
                return "Status(initialized)"
            parts = [f"{Path(p).name}: {s}" for p, s in self._state.items()]
            return f"Status({', '.join(parts)})"

    def __init__(self, bench_dir: str | Path | None = None):
        self._store = Store(bench_dir)
        self._technician = Technician(self._store, self._on_status)
        self._mem: dict[str, Sample] = {}
        self._evaluation_mem: dict[str, Evaluation] = {}
        self._affected: dict[str, set[str]] = {}
        self._current_path: str | None = None
        self.integrity = self.Integrity()
        self.status = self.Status()

    # ── Status callback (given to Technician) ──

    def _on_status(self, path: str, integrity: str, status: str):
        """Called by the Technician to update labels."""
        if integrity:
            self.integrity._state[path] = integrity
        if status:
            self.status._state[path] = status
        # If background reload completed (VERIFIED + LIVE), swap in the result
        if integrity == Technician.VERIFIED and status == Technician.LIVE:
            bg = getattr(self._technician, "_bg_result", None)
            if bg is not None and bg[0] == path:
                self._mem[path] = bg[1]
                self._technician._bg_result = None
                # Invalidate evaluation — stale after background swap
                self._evaluation_mem.pop(path, None)

    # ── Prepare ──

    def prepare(self, path: str) -> "Bench":
        """Prepare a .pltg file for observation. Returns self for chaining."""
        path = str(Path(path).resolve())
        self._current_path = path
        sample, affected = self._technician.prepare(path, self._mem.get(path))
        self._mem[path] = sample
        if affected is not None:
            self._affected[path] = affected
            self._evaluation_mem.pop(path, None)
        self._populate_scopes(path)
        return self

    def _require_current(self) -> str:
        if self._current_path is None:
            raise RuntimeError("No sample prepared. Call bench.prepare(path) first.")
        return self._current_path

    # ── Observe: structure ──

    def lens(self, path: str | None = None) -> Lens:
        """Structural observation — a Lens with MDebuggerPerspective."""
        path = str(Path(path).resolve()) if path else self._require_current()
        if path not in self._mem:
            self.prepare(path)
        _, _, structure, loader = self._mem[path]
        return Lens(structure, [MDebuggerPerspective(loader)])

    def dissect(self, diff_name: str, path: str | None = None, perspectives: list | None = None) -> Hologram:
        """Dissect a diff into a Hologram — two lenses, one per side."""
        path = str(Path(path).resolve()) if path else self._require_current()
        result = self._ensure_live_result(path)
        engine = result.system.engine
        diff = engine.diffs[diff_name]
        from .probe_core_to_consequence import probe as _probe

        l_struct = _probe(diff["replace"], engine)
        r_struct = _probe(diff["with"], engine)
        _, _, _, loader = self._mem[path]
        persp = perspectives or [MDebuggerPerspective(loader)]
        left = Lens(l_struct, list(persp))
        right = Lens(r_struct, list(persp))
        return Hologram([left, right], name=diff_name, labels=[diff["replace"], diff["with"]])

    def compose(self, *names: str, path: str | None = None, perspectives: list | None = None) -> Hologram:
        """Compose N system names into a Hologram — one lens per name."""
        path = str(Path(path).resolve()) if path else self._require_current()
        result = self._ensure_live_result(path)
        engine = result.system.engine
        _, _, _, loader = self._mem[path]
        persp = perspectives or [MDebuggerPerspective(loader)]
        from .probe_core_to_consequence import probe as _probe

        lenses = []
        for name in names:
            structure = _probe(name, engine)
            lenses.append(Lens(structure, list(persp)))
        return Hologram(lenses, labels=list(names))

    # ── Observe: health ──

    def evaluate(self, path: str | None = None) -> Evaluation:
        """Consistency observation — a Evaluation with focus, search, filtering.

        Cached in memory and on disk. Same Merkle root = same evaluation.
        Incremental: when only some nodes changed, patches only affected diffs.
        """
        path = str(Path(path).resolve()) if path else self._require_current()

        # Memory cache
        if path in self._evaluation_mem:
            return self._evaluation_mem[path]

        # Disk cache — exact Merkle match
        cached = self._mem.get(path)
        if cached:
            merkle_root = cached[1].hash
            disk_dx = self._store.load_diagnosis(path, merkle_root)
            if disk_dx is not None:
                self._evaluation_mem[path] = disk_dx
                return disk_dx

        # Incremental: stale evaluation + known affected set from prepare
        affected = self._affected.get(path)
        if affected is not None:
            old_dx = self._store.load_stale_diagnosis(path)
            if old_dx is not None:
                result = self._ensure_live_result(path)
                engine = result.system.engine

                diffs_to_patch: set[str] = set()
                for name in affected:
                    diffs_to_patch |= engine.diff_refs.get(name, set())

                if diffs_to_patch:
                    log.info("Incremental evaluate: %d/%d diffs", len(diffs_to_patch), len(engine.diffs))
                    lc = result.consistency_incremental(diffs_to_patch)
                    dx = old_dx.incremental(diffs_to_patch, lc)
                    self._evaluation_mem[path] = dx
                    self._save_evaluation(path, dx)
                    self._affected.pop(path, None)
                    return dx

        # Cold — full consistency
        result = self._ensure_live_result(path)
        lc = result.consistency()
        dx = Evaluation.from_report(lc, result)
        self._evaluation_mem[path] = dx
        self._save_evaluation(path, dx)
        return dx

    def _populate_scopes(self, path: str):
        """Register all search scopes after prepare."""
        self._populate_search_docs(path)
        dx = self.evaluate(path)
        self._register_evaluation_scope(path, dx)

    def _populate_search_docs(self, path: str):
        """Add engine documents to the search index."""
        result = self._ensure_live_result(path)
        search = self._search_engine(path)
        for doc_name, doc_text in result.system.engine.documents.items():
            if doc_name not in search._index.documents:
                search._index.add(doc_name, doc_text)

    def _register_evaluation_scope(self, path: str, dx: Evaluation):
        """Register evaluation as a search scope."""
        from .evaluation import EvaluationSearchSystem

        ds = EvaluationSearchSystem(dx)
        self._search_engine(path).register_scope("evaluation", ds._system)

    # ── Search ──

    def search(
        self, query: str, max_lines: int = 20, max_callers: int = 5, offset: int = 0, rank: str = "callers"
    ) -> dict:
        """Full-text search across all loaded documents with pltg provenance."""
        path = self._require_current()
        if path not in self._mem:
            self.prepare(path)
        return self._search_engine(path).query(
            query, max_lines=max_lines, max_callers=max_callers, offset=offset, rank=rank
        )

    def _search_engine(self, path: str):
        if not hasattr(self, "_search_mem"):
            self._search_mem: dict[str, "Search"] = {}
        if path not in self._search_mem:
            from .search import Search

            self._search_store = SearchStore(self._store, path)
            self._search_mem[path] = Search(store=self._search_store)
        return self._search_mem[path]

    @property
    def index(self):
        """The Search index for the current sample."""
        path = self._require_current()
        return self._search_engine(path)

    # ── Access ──

    def result(self, path: str | None = None) -> LazyLoadResult:
        """The LazyLoadResult for the sample. Triggers full load if needed."""
        path = str(Path(path).resolve()) if path else self._require_current()
        return self._ensure_live_result(path)

    @property
    def engine(self):
        """The engine of the current sample."""
        return self.result().system.engine

    # ── Cache management ──

    def invalidate(self, path: str | None = None):
        """Clear cache for a path, or all if None."""
        if path is None:
            self._mem.clear()
            self._evaluation_mem.clear()
            self._technician.invalidate()
            if hasattr(self, "_search_mem"):
                self._search_mem.clear()
        else:
            path = str(Path(path).resolve())
            self._mem.pop(path, None)
            self._evaluation_mem.pop(path, None)
            self._technician.invalidate(path)
            if hasattr(self, "_search_mem"):
                self._search_mem.pop(path, None)

    def purge(self):
        """Purge all caches — memory and disk. Nuclear option."""
        self._mem.clear()
        self._evaluation_mem.clear()
        self._affected.clear()
        if hasattr(self, "_search_mem"):
            self._search_mem.clear()
        self._store.remove_all()
        self._technician.invalidate()

    # ── Internal ──

    def _ensure_live_result(self, path: str) -> LazyLoadResult:
        """Get a live LazyLoadResult (with engine)."""
        if path not in self._mem:
            self.prepare(path)
        result, sample = self._technician.ensure_live(path, self._mem.get(path))
        self._mem[path] = sample
        return result

    def _save_evaluation(self, path: str, dx: Evaluation):
        cached = self._mem.get(path)
        merkle_root = cached[1].hash if cached else ""
        self._store.save_diagnosis(path, merkle_root, dx)
