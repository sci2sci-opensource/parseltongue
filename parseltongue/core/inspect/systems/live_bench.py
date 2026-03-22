"""LiveBench — bench_pg system with the loaded sample as a scope.

Copies the frozen bench system (already loaded) and registers the sample's
live system as a "sample" scope. Has all bench_pg axioms/terms plus access
to the real engine data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .bench_system import BenchSystem

if TYPE_CHECKING:
    from parseltongue.core.loader.lazy_loader import LazyLoadResult

    from .frozen_bench import FrozenBench


class LiveBench(BenchSystem):
    """Live bench system — copied from frozen, sample registered as scope."""

    def __init__(self, result: "LazyLoadResult", frozen: "FrozenBench"):
        self._loader = frozen._loader
        self.system = frozen.system.copy(name="LiveBench", overridable=True)  # type: ignore[assignment]
        self.result = result
        self.register_scope("sample", result.system)
