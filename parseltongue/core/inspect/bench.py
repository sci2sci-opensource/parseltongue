"""Bench — workstation for observing .pltg samples.

Prepare a sample, then observe: ``lens()`` for structure,
``evaluate()`` for health. Backed by Merkle tree caching.

The Bench owns sample status and integrity labels. A Technician
handles loading (cold, cache hit, hot-patch, background reload),
scope registration, and screening cache. A Store handles
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
from .screen import Screen
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

    def prepare(self, path: str, effects: dict | None = None) -> "Bench":
        """Prepare a .pltg file for observation. Returns self for chaining.

        Args:
            effects: Optional dict of effect name → callable for this path.
                     Different paths can have different effects.
        """
        path = str(Path(path).resolve())
        if effects is not None:
            self._technician._effects[path] = effects
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

    def stain(
        self,
        *names: str,
        path: str | None = None,
        perspectives: list | None = None,
        capture: str | int = "names",
        store: str | int = "names",
    ) -> Hologram:
        """Live-probe N terms with tracing — one lens per name.

        Traces the engine (auto-detects Tracer vs Stain), re-evaluates
        each term's theorem WFF to capture runtime edges, then builds
        lenses with live_probe.

        Parameters:
            names: Term names to probe (theorems are re-evaluated under trace).
            capture: Capture mode (only affects legacy Stain engine).
            store: live_probe store mode ("names", "heads", "all", or int N).
        """
        path = str(Path(path).resolve()) if path else self._require_current()
        result = self._ensure_live_result(path)
        engine = result.system.engine
        _, _, _, loader = self._mem[path]
        persp = perspectives or [MDebuggerPerspective(loader)]
        from .vital import live_probe, trace_engine

        traced = trace_engine(engine, names=list(names), capture=capture)

        lenses = []
        for name in names:
            structure = live_probe(name, engine, traced, store=store)
            lenses.append(Lens(structure, list(persp)))
        return Hologram(lenses, labels=list(names))

    # ── Observe: health ──

    def screen(self, path: str | None = None) -> Screen:
        """Consistency observation — a Screen with focus, search, filtering."""
        path = str(Path(path).resolve()) if path else self._require_current()
        if path not in self._mem:
            self.prepare(path)
        return self._technician._load_screen(path, self._mem.get(path))

    # Backwards compat
    evaluate = screen

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
        """Evaluate an S-expression. Pure — never polluted by interpret()."""
        from parseltongue.core.lang import PGStringParser

        path = self._require_current()
        loader, system = self._ensure_eval_system(path)
        expr = PGStringParser.translate(query)
        expr = loader.prepare_script(expr, system)
        return system.engine.evaluate(expr)

    def interpret(self, query: str):
        """Interpret a directive or expression. Accumulates state; clean() resets."""
        path = self._require_current()
        _, system = self._ensure_experiment_system(path)
        _, result = system.interpret(query)
        return result

    def _prepare_bench_system(self, path: str):
        """Get the best available bench system — live if ready, frozen otherwise.

        Scopes (lens, screen, search, ops, viz) are registered by the
        Technician's _register_scopes — no need to re-register here.
        """
        live = self._technician._live.get(path)
        if live:
            return live, False

        # Fall back to frozen
        frozen = self._technician._frozen
        if frozen:
            log.warning("Serving from frozen system (live still loading)")
            return frozen, True

        raise RuntimeError(f"No bench system for {path} — is it loaded?")

    def _copy_bench_system(self, path: str, name: str) -> tuple:
        """Copy the best available bench system with scopes + count operator."""
        from parseltongue.core.atoms import Symbol

        bench_sys, is_frozen = self._prepare_bench_system(path)
        copy = bench_sys.system.copy(name=name, overridable=True)
        copy.engine.env[Symbol("count")] = lambda *args: (
            len(args[0]) if args and isinstance(args[0], (dict, list)) else 0
        )
        return bench_sys._loader, copy

    def _ensure_eval_system(self, path: str):
        """Cached clean copy of live. Never mutated."""
        if not hasattr(self, "_eval_mem"):
            self._eval_mem: dict[str, tuple] = {}
        if path not in self._eval_mem:
            self._eval_mem[path] = self._copy_bench_system(path, "eval")
        return self._eval_mem[path]

    def _ensure_experiment_system(self, path: str):
        """Cached copy of live for interpret(). clean() resets it."""
        if not hasattr(self, "_experiment_mem"):
            self._experiment_mem: dict[str, tuple] = {}
        if path not in self._experiment_mem:
            self._experiment_mem[path] = self._copy_bench_system(path, "experiment")
        return self._experiment_mem[path]

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

    @property
    def eval_system(self):
        """The eval system — clean copy of live with scopes registered."""
        path = self._require_current()
        _, system = self._ensure_eval_system(path)
        return system

    # ── Cache management ──

    def clean(self):
        """Reset the experiment system. Eval and live stay warm."""
        if hasattr(self, "_experiment_mem"):
            self._experiment_mem.clear()

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
