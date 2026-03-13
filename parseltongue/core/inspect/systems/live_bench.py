"""LiveBench — bench_pg system with the loaded sample as a scope.

Loads bench.pltg the same way FrozenBench does (own loader, own system),
then registers the sample's live system as a "sample" scope. Has all
bench_pg axioms/terms plus access to the real engine data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .bench_system import BenchSystem

if TYPE_CHECKING:
    from parseltongue.core.loader.lazy_loader import LazyLoadResult
    from parseltongue.core.system import System


class LiveBench(BenchSystem):
    """Live bench system — bench_pg loaded, sample registered as scope."""

    def __init__(self, result: "LazyLoadResult", bench_pg_path: str, lib_paths: list[str]):
        from parseltongue.core.loader.lazy_loader import LazyLoader

        self._loader = LazyLoader(lib_paths=lib_paths)
        self._loader.load_main(bench_pg_path)
        self.system: System = self._loader.last_result.system  # type: ignore[union-attr]
        self.result = result
        self.register_scope("sample", result.system)
