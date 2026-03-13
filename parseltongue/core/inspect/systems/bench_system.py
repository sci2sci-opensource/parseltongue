"""BenchSystem — base class for frozen and live bench systems.

Provides scope registration: ``register_scope(name, system)``
wires a scope system into the engine env so that ``(name expr)``
evaluates in the scope and returns raw pltg results.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parseltongue.core.system import System


class BenchSystem:
    """Base for bench systems. Provides scope registration."""

    system: System

    def register_scope(self, name: str, scope_system):
        """Register a scope system as a callable in engine env.

        Calls scope_system.evaluate(expr) which returns raw pltg results
        (posting sets, scalars, lists — whatever the system produces).
        """
        from parseltongue.core.atoms import Symbol

        def _scope_fn(_name, *args):
            result = None
            for arg in args:
                if isinstance(arg, list):
                    result = scope_system.evaluate(arg)
                else:
                    result = arg
            return result

        self.system.engine.env[Symbol(name)] = _scope_fn
