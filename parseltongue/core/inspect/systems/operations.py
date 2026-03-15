"""OperationsSystem — sentence composition via pltg axioms.

Loads bench_pg/ops.pltg which imports std + tag modules, providing
or/and/not/count/limit as rewrite axioms over sentence lists.

Implements BenchSubsystem so it registers as a normal scope on
SearchSystem.  PostingMorphism dispatches mixed-tag results (ln, dx,
sr, hn) to registered subsystem morphisms — same pattern as
SearchPostingMorphism.
"""

from __future__ import annotations

from typing import Any

from parseltongue.core.atoms import Symbol
from parseltongue.core.system import System

from .bench_system import BenchSubsystem, Posting


class _OpsPostingMorphism:
    """Dispatch morphism — routes mixed-tag forms to registered subsystem morphisms."""

    def __init__(self):
        self._dispatch: dict[Symbol, BenchSubsystem] = {}

    def register(self, subsystem: BenchSubsystem):
        self._dispatch[subsystem.tag] = subsystem

    def unregister(self, tag: Symbol):
        self._dispatch.pop(tag, None)

    def transform(self, posting: Posting) -> list:
        result = []
        for subsystem in self._dispatch.values():
            result.extend(subsystem.posting_morphism.transform(posting))
        return result

    def inverse(self, forms: list) -> Posting:
        posting: Posting = {}
        by_tag: dict[Symbol, list] = {}
        for item in forms:
            if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[0], Symbol):
                by_tag.setdefault(item[0], []).append(item)
        for tag, items in by_tag.items():
            subsystem = self._dispatch.get(tag)
            if subsystem is None:
                base = Symbol(str(tag).rsplit(".", 1)[-1])
                subsystem = self._dispatch.get(base)
            if subsystem is not None:
                posting.update(subsystem.posting_morphism.inverse(items))
        return posting


class OperationsSystem:
    """BenchSubsystem: pltg System with std + bench_pg ops."""

    tag = Symbol("ops")

    def _scope(self, name, *args):
        if name not in self._scopes:
            raise KeyError(f"Unknown scope: {name!r}. Registered: {list(self._scopes)}")
        scope_system = self._scopes[name]
        result = None
        for arg in args:
            if isinstance(arg, (list, tuple)):
                result = scope_system.evaluate(arg)
            else:
                result = arg
        return result

    def __init__(self, lib_paths: list[str] | None = None):
        from pathlib import Path

        from parseltongue.core.loader.lazy_loader import LazyLoader

        bench_pg_dir = str(Path(__file__).resolve().parent.parent / "bench_pg")
        ops_pltg = str(Path(bench_pg_dir) / "ops.pltg")

        all_paths = list(lib_paths or []) + [bench_pg_dir]
        loader = LazyLoader(lib_paths=all_paths)
        loader.load_main(ops_pltg, name="Operations", strict=False)
        assert loader.last_result is not None
        self.system: System = loader.last_result.system
        self.posting_morphism = _OpsPostingMorphism()
        self._scopes: dict[str, Any] = {}
        self.system.engine.env[Symbol("scope")] = self._scope

    def register_scope(self, name: str, scope_system):
        """Register a scope so ops can cross into lens/evaluation/search."""
        self._scopes[name] = scope_system
        if hasattr(scope_system, 'tag') and hasattr(scope_system, 'posting_morphism'):
            self.posting_morphism.register(scope_system)

        self.system.engine.env[Symbol(name)] = lambda *args: self._scope(name, *args)

    def evaluate(self, expr, local_env=None):
        return self.system.evaluate(expr)
