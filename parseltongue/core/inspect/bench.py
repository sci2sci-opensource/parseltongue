"""Bench — workstation for observing .pltg samples.

Prepare a sample, then observe: ``lens()`` for structure,
``evaluate()`` for health. Backed by Merkle tree caching.

The Bench owns sample status and integrity labels. A Technician
handles loading (cold, cache hit, hot-patch, background reload),
scope registration, and evaluation caching. A Store handles
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
from .store import Store
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

    #: Default lib paths — includes parseltongue core/std for standard library imports.
    STD_PATH = str(Path(__file__).resolve().parent.parent)
    #: bench.pltg — right next to this file, imports bench_pg/*.pltg modules.
    BENCH_PG = str(Path(__file__).resolve().parent / "bench.pltg")
    BENCH_PG_DIR = str(Path(__file__).resolve().parent)

    def __init__(self, bench_dir: str | Path | None = None, lib_paths: list[str] | None = None):
        self._store = Store(bench_dir)
        self._lib_paths = lib_paths if lib_paths is not None else [self.STD_PATH]
        self._technician = Technician(
            self._store,
            self._on_status,
            lib_paths=self._lib_paths + [self.BENCH_PG_DIR],
            bench_pg=self.BENCH_PG,
        )
        self._mem: dict[str, Sample] = {}
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
        # Background reload completed — swap in result
        if integrity == Technician.VERIFIED and status == Technician.LIVE:
            bg = getattr(self._technician, "_bg_result", None)
            if bg is not None and bg[0] == path:
                self._mem[path] = bg[1]
                self._technician._bg_result = None

    # ── Prepare ──

    def prepare(self, path: str) -> "Bench":
        """Prepare a .pltg file for observation. Returns self for chaining."""
        path = str(Path(path).resolve())
        self._current_path = path
        sample, _ = self._technician.prepare(path, self._mem.get(path))
        self._mem[path] = sample
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
        """Consistency observation — an Evaluation with focus, search, filtering."""
        path = str(Path(path).resolve()) if path else self._require_current()
        if path not in self._mem:
            self.prepare(path)
        return self._technician._load_evaluate(path, self._mem.get(path))

    # ── Search ──

    def search(
        self, query: str, max_lines: int = 20, max_callers: int = 5, offset: int = 0, rank: str = "callers"
    ) -> dict:
        """Full-text search across all loaded documents with pltg provenance."""
        path = self._require_current()
        if path not in self._mem:
            self.prepare(path)
        return self._technician.search_engine(path).query(
            query, max_lines=max_lines, max_callers=max_callers, offset=offset, rank=rank
        )

    def eval(self, query: str):
        """Evaluate an S-expression in the eval system (main + std + scopes)."""
        from parseltongue.core.lang import PGStringParser

        path = self._require_current()
        if path not in self._mem:
            self.prepare(path)
        eval_loader, eval_system = self._ensure_eval_system(path)
        expr = PGStringParser.translate(query)
        expr = eval_loader.prepare_script(expr, eval_system)
        return eval_system.engine.evaluate(expr)

    def _ensure_eval_system(self, path: str):
        """Build or return cached eval system: live bench + scopes."""
        if not hasattr(self, "_eval_sys_mem"):
            self._eval_sys_mem: dict[str, tuple] = {}
        if path in self._eval_sys_mem:
            return self._eval_sys_mem[path]

        from parseltongue.core.atoms import Symbol

        live = self._technician._live.get(path)
        if not live:
            raise RuntimeError(f"No live system for {path} — is it loaded?")

        system = live.system
        engine = system.engine

        # Register scopes
        live.register_scope("lens", self.lens(path).search_system)
        live.register_scope("evaluation", self.evaluate(path).search_system)
        live.register_scope("search", self._technician.search_engine(path)._system)
        engine.env[Symbol("count")] = lambda *args: len(args[0]) if args and isinstance(args[0], (dict, list)) else 0

        self._eval_sys_mem[path] = (live._loader, system)
        return live._loader, system

    @property
    def index(self):
        """The Search index for the current sample."""
        path = self._require_current()
        return self._technician.search_engine(path)

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
            self._technician.invalidate()
        else:
            path = str(Path(path).resolve())
            self._mem.pop(path, None)
            self._technician.invalidate(path)

    def purge(self):
        """Purge all caches — memory and disk. Nuclear option."""
        self._mem.clear()
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
