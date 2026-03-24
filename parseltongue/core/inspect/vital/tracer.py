"""Tracer expression — activates engine-native dependency tracing.

The stack engine carries trace data directly on its continuation stack
via _K_CONTEXT frames.  The Tracer toggles this:

    express()  — knock-in: enable trace gene, engine records edges
    suppress() — silence: disable tracing, flush & extract edges

No monkey-patching, no observer hooks, no context inference.
The engine does all the work.

Usage::

    tracer = Tracer(engine)
    tracer.express()
    engine.evaluate(Symbol("my-theorem"))
    tracer.suppress()
    print(tracer.edges)

Or as context manager::

    with Tracer(engine) as t:
        engine.evaluate(Symbol("my-theorem"))
    print(t.edges)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Edge:
    """A runtime dependency edge: caller resolved/used callee."""

    caller: str
    callee: str
    kind: str = "resolve"  # resolve, effect, rewrite


class Tracer:
    """Tracer expression — toggles engine-native dependency tracing.

    express() activates tracing (the trace gene is expressed).
    suppress() deactivates and extracts edges (gene suppression).

    Engines that support tracing expose ``_tracing``, ``_trace_log``,
    ``_tracer_stack``, ``_trace_context``, ``_trace_current``.
    """

    def __init__(self, engine):
        self._engine = engine
        self._edges: set[Edge] | None = None
        self._expressed = False

    @staticmethod
    def supported(engine) -> bool:
        """Does this engine support native tracing?"""
        return hasattr(engine, "_tracing")

    def express(self) -> "Tracer":
        """Knock-in: activate trace gene. Engine starts recording."""
        self._engine._tracing = True
        self._engine._trace_log = []
        self._engine._trace_context = None
        self._engine._trace_current = None
        self._engine._tracer_stack = []
        self._edges = None
        self._expressed = True
        return self

    def suppress(self) -> "Tracer":
        """Silence: deactivate tracing, flush stale frames, extract edges."""
        if not self._expressed:
            return self
        self._engine._tracing = False
        # Flush any remaining tracer_stack entries (from exceptions unwinding _eval)
        for name, entries in self._engine._tracer_stack:
            self._engine._trace_log.append((name, entries))
        self._engine._tracer_stack.clear()
        self._engine._trace_context = None
        self._engine._trace_current = None
        self._extract()
        self._expressed = False
        return self

    def __enter__(self) -> "Tracer":
        self.express()
        return self

    def __exit__(self, *exc) -> None:
        self.suppress()

    def _extract(self):
        """Convert trace_log entries into Edge objects."""
        edges: set[Edge] = set()
        for ctx_name, entries in self._engine._trace_log:
            for kind, target in entries:
                if target != ctx_name:
                    edges.add(Edge(ctx_name, target, kind))
        self._edges = edges

    @property
    def edges(self) -> set[Edge]:
        if self._edges is None:
            self._extract()
        return self._edges  # type: ignore[return-value]

    @property
    def traces(self) -> list:
        """Empty list — Tracer doesn't record expression-level traces.

        Present for API compatibility with Stain (live_probe checks this).
        """
        return []

    @property
    def trace_log(self) -> list:
        """Raw trace log: [(context_name, [(kind, target), ...]), ...]"""
        return self._engine._trace_log

    def edge_dict(self) -> dict[str, set[str]]:
        """Edges as caller -> set of callees."""
        d: dict[str, set[str]] = {}
        for e in self.edges:
            d.setdefault(e.caller, set()).add(e.callee)
        return d

    def edge_tuples(self) -> set[tuple[str, str, str]]:
        """Edges as (caller, callee, kind) tuples for easy comparison."""
        return {(e.caller, e.callee, e.kind) for e in self.edges}

    def summary(self) -> str:
        """Human-readable summary."""
        by_kind: dict[str, int] = {}
        callers: set[str] = set()
        callees: set[str] = set()
        for e in self.edges:
            by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
            callers.add(e.caller)
            callees.add(e.callee)
        parts = [f"{len(self.edges)} edges ({len(callers)} callers, {len(callees)} callees)"]
        for kind, count in sorted(by_kind.items()):
            parts.append(f"  {kind}: {count}")
        return "\n".join(parts)

    def clear(self):
        """Clear accumulated trace data."""
        self._engine._trace_log = []
        self._edges = None
