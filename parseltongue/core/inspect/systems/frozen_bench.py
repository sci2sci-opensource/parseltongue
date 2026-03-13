"""FrozenBench — synthetic System loaded with std + bench_pg.

Separate loader, separate system. Has sr/ln/dx/hn pltg forms and
accessor axioms. No live engine — available immediately after prepare.
Scope operators inject data (lens structure, evaluation items) into it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .bench_system import BenchSystem

if TYPE_CHECKING:
    from parseltongue.core.system import System


class FrozenBench(BenchSystem):
    """Frozen bench system — loaded std + bench_pg, no live engine."""

    def __init__(self, bench_pg_path: str, lib_paths: list[str]):
        from parseltongue.core.loader.lazy_loader import LazyLoader

        self._loader = LazyLoader(lib_paths=lib_paths)
        self._loader.load_main(bench_pg_path)
        self.system: System = self._loader.last_result.system  # type: ignore[union-attr]
