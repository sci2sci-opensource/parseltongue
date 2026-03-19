"""Stain — instruments an engine to capture runtime dependency edges.

Patches engine._eval and engine._rewrite to record:
  1. Symbol resolution: term/theorem/fact lookups
  2. Effect invocation: callable dispatch with args
  3. Rewrite axiom application: which axiom fired, what it matched
  4. Full evaluation traces (configurable depth)

The stain does NOT reimplement engine logic. It records edges before
delegating to the originals. Since Python instance attribute lookup
finds patched methods first, all recursive self._eval / self._rewrite
calls go through the stain.

Capture modes (``capture`` parameter)::

    "names"   — (default) only named entities (terms/theorems/facts/axioms)
    "heads"   — named + head symbol of every list expression
    "all"     — every _eval call, full expressions
    int N     — every _eval call up to N levels from nearest named context

Usage::

    with Stain(engine, capture="all") as stain:
        engine.evaluate(some_expr)
    print(stain.summary())
    # stain.edges — named dependency edges
    # stain.traces — full evaluation trace entries
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from parseltongue.core.atoms import Symbol
from parseltongue.core.engine import Engine

log = logging.getLogger("parseltongue.vital.stain")


@dataclass(frozen=True)
class Edge:
    """A runtime dependency edge: caller resolved callee."""

    caller: str
    callee: str
    kind: str = "resolve"  # resolve, effect, rewrite


@dataclass(frozen=True)
class Trace:
    """A single _eval invocation record.

    context: nearest named ancestor (or None for top-level)
    expr_s: to_sexp of the input expression
    result_s: to_sexp of the result (filled after eval)
    depth: call depth from the nearest named context
    """

    context: str | None
    expr_s: str
    result_s: str
    depth: int


def _truncate_sexp(expr, max_depth: int = 3) -> str:
    """to_sexp with depth truncation to avoid huge strings."""

    def _trunc(e, d):
        if d > max_depth:
            return "..."
        if isinstance(e, (list, tuple)):
            if not e:
                return "()"
            parts = [_trunc(x, d + 1) for x in e]
            return "(" + " ".join(parts) + ")"
        if isinstance(e, bool):
            return "true" if e else "false"
        if isinstance(e, str) and not isinstance(e, Symbol):
            if len(e) > 60:
                return f'"{e[:57]}..."'
            escaped = e.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        s = str(e)
        return s if len(s) <= 80 else s[:77] + "..."

    return _trunc(expr, 0)


class Stain:
    """Vital stain — captures runtime resolution edges from an engine.

    Patches engine._eval and engine._rewrite to maintain a call context
    stack and record edges. Non-destructive: remove() restores originals.

    Parameters:
        engine: The engine to instrument.
        capture: Controls trace granularity:
            "names" — only named entity edges (default, no traces)
            "heads" — edges + traces for list expression heads only
            "all"   — edges + traces for every _eval call
            int N   — edges + traces up to N call levels from named context
    """

    def __init__(self, engine: Engine, capture: str | int = "names"):
        self._engine = engine
        self._original_eval = None
        self._original_rewrite = None
        self._edges: set[Edge] = set()
        self._traces: list[Trace] = []
        self._context_stack: list[str] = []
        self._depth_stack: list[int] = []  # depth from nearest named context
        self._applied = False
        self._capture = capture

    @property
    def edges(self) -> set[Edge]:
        return self._edges

    @property
    def traces(self) -> list[Trace]:
        return self._traces

    @property
    def capture(self) -> str | int:
        return self._capture

    def edge_dict(self) -> dict[str, set[str]]:
        """Edges as caller -> set of callees."""
        d: dict[str, set[str]] = {}
        for e in self._edges:
            d.setdefault(e.caller, set()).add(e.callee)
        return d

    def _should_trace(self, depth_from_context: int) -> bool:
        """Should we record a trace entry at this depth?"""
        c = self._capture
        if c == "names":
            return False
        if c == "all":
            return True
        if c == "heads":
            return True  # caller filters to heads only
        if isinstance(c, int):
            return depth_from_context <= c
        return False

    def apply(self) -> "Stain":
        """Apply the stain — start recording. Returns self for chaining."""
        if self._applied:
            return self
        self._original_eval = self._engine._eval
        self._original_rewrite = self._engine._rewrite
        engine = self._engine
        stain = self

        # ── Stained _eval ──

        def _stained_eval(expr, env, axiom_scope=None, restricted=False):
            context = stain._context_stack[-1] if stain._context_stack else None
            cur_depth = stain._depth_stack[-1] if stain._depth_stack else 0
            push = None
            trace_this = False

            if isinstance(expr, Symbol):
                name = str(expr)

                # Symbol about to resolve to term/theorem/fact — record edge
                if not restricted:
                    if name in engine.terms:
                        if context and context != name:
                            stain._edges.add(Edge(context, name, "resolve"))
                        if engine.terms[name].definition is not None:
                            push = name
                    elif name in engine.theorems:
                        if context and context != name:
                            stain._edges.add(Edge(context, name, "resolve"))
                        push = name
                    elif name in engine.facts:
                        if context and context != name:
                            stain._edges.add(Edge(context, name, "resolve"))

                # Trace: symbols are always interesting
                trace_this = stain._should_trace(cur_depth)

            elif isinstance(expr, (list, tuple)) and expr:
                head = expr[0]
                if isinstance(head, Symbol):
                    head_name = str(head)
                    if context and context != head_name:
                        # Term used as callable head (effect/operator)
                        if head_name in engine.terms:
                            stain._edges.add(Edge(context, head_name, "effect"))
                        # Also record edges for Symbol args that are facts/terms
                        for arg in expr[1:]:
                            if isinstance(arg, Symbol):
                                arg_name = str(arg)
                                if arg_name in engine.facts or arg_name in engine.terms or arg_name in engine.theorems:
                                    stain._edges.add(Edge(context, arg_name, "resolve"))

                # Trace: for "heads" mode, only record if it's a list with a head
                if stain._capture == "heads":
                    trace_this = isinstance(expr, (list, tuple)) and bool(expr)
                else:
                    trace_this = stain._should_trace(cur_depth)

            elif stain._capture not in ("names", "heads"):
                # Scalars (strings, numbers, bools) — trace if depth allows
                trace_this = stain._should_trace(cur_depth)

            # Record trace before delegating
            trace_idx = -1
            if trace_this:
                trace_idx = len(stain._traces)
                # Placeholder — result_s filled after eval
                stain._traces.append(
                    Trace(
                        context=context,
                        expr_s=_truncate_sexp(expr),
                        result_s="",
                        depth=cur_depth,
                    )
                )

            # Delegate to original
            if push:
                stain._context_stack.append(push)
                stain._depth_stack.append(0)  # reset depth for new named context
                try:
                    result = stain._original_eval(expr, env, axiom_scope, restricted)
                finally:
                    stain._context_stack.pop()
                    stain._depth_stack.pop()
            else:
                stain._depth_stack.append(cur_depth + 1)
                try:
                    result = stain._original_eval(expr, env, axiom_scope, restricted)
                finally:
                    stain._depth_stack.pop()

            # Fill in result
            if trace_idx >= 0:
                old = stain._traces[trace_idx]
                stain._traces[trace_idx] = Trace(
                    context=old.context,
                    expr_s=old.expr_s,
                    result_s=_truncate_sexp(result),
                    depth=old.depth,
                )

            return result

        # ── Stained _rewrite ──

        def _stained_rewrite(expr, depth=0, axiom_scope=None, _prev=None):
            context = stain._context_stack[-1] if stain._context_stack else None

            # Before delegating, snapshot axiom names so we can detect which fired
            # We intercept the result: if it differs from input, a rewrite happened
            result = stain._original_rewrite(expr, depth, axiom_scope, _prev)

            if result != expr and context:
                # A rewrite happened — figure out which axiom matched
                # by trying to match the same way the engine does
                from parseltongue.core.engine import EQ, match

                if axiom_scope is not None:
                    rules = axiom_scope
                else:
                    rules = list(engine.axioms.values()) + list(engine.theorems.values())
                for rule in rules:
                    wff = rule.wff
                    if not (isinstance(wff, (list, tuple)) and len(wff) == 3 and wff[0] == EQ):
                        continue
                    lhs = wff[1]
                    if not isinstance(lhs, (list, tuple)):
                        continue
                    bindings = match(lhs, expr)
                    if bindings is not None:
                        stain._edges.add(Edge(context, rule.name, "rewrite"))
                        # Also record edges to any named values in the bindings
                        for var, val in bindings.items():
                            if isinstance(val, Symbol):
                                val_name = str(val)
                                if val_name in engine.facts:
                                    stain._edges.add(Edge(context, val_name, "resolve"))
                                elif val_name in engine.terms:
                                    stain._edges.add(Edge(context, val_name, "resolve"))
                        break

            return result

        self._engine._eval = _stained_eval
        self._engine._rewrite = _stained_rewrite
        self._applied = True
        log.info("Stain applied to engine (capture=%s)", self._capture)
        return self

    def remove(self) -> "Stain":
        """Remove the stain — restore originals."""
        if self._applied:
            if self._original_eval is not None:
                self._engine._eval = self._original_eval
                self._original_eval = None
            if self._original_rewrite is not None:
                self._engine._rewrite = self._original_rewrite
                self._original_rewrite = None
            self._applied = False
            log.info(
                "Stain removed from engine, %d edges, %d traces captured",
                len(self._edges),
                len(self._traces),
            )
        return self

    def clear(self) -> "Stain":
        """Clear captured edges and traces without removing the stain."""
        self._edges.clear()
        self._traces.clear()
        self._context_stack.clear()
        self._depth_stack.clear()
        return self

    def push_context(self, name: str):
        """Manually push an evaluation context (e.g. for a derive being evaluated)."""
        self._context_stack.append(name)
        self._depth_stack.append(0)

    def pop_context(self):
        """Pop the current evaluation context."""
        if self._context_stack:
            self._context_stack.pop()
        if self._depth_stack:
            self._depth_stack.pop()

    def __enter__(self):
        self.apply()
        return self

    def __exit__(self, *exc):
        self.remove()
        return False

    def summary(self) -> str:
        """Human-readable summary of captured edges and traces."""
        by_kind: dict[str, int] = {}
        callers: set[str] = set()
        callees: set[str] = set()
        for e in self._edges:
            by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
            callers.add(e.caller)
            callees.add(e.callee)
        parts = [f"{len(self._edges)} edges ({len(callers)} callers, {len(callees)} callees)"]
        for kind, count in sorted(by_kind.items()):
            parts.append(f"  {kind}: {count}")
        if self._traces:
            # Group traces by context
            by_ctx: dict[str | None, int] = {}
            for t in self._traces:
                by_ctx[t.context] = by_ctx.get(t.context, 0) + 1
            parts.append(f"{len(self._traces)} traces across {len(by_ctx)} contexts")
            for ctx, count in sorted(by_ctx.items(), key=lambda x: -x[1])[:10]:
                parts.append(f"  {ctx or '<top>': <40s} {count}")
        return "\n".join(parts)

    def traces_for(self, context: str) -> list[Trace]:
        """All traces under a specific named context."""
        return [t for t in self._traces if t.context == context]

    def trace_tree(self, context: str | None = None) -> dict:
        """Build a nested dict of traces grouped by context and depth.

        Returns {context: [{expr_s, result_s, depth}, ...], ...}
        """
        tree: dict[str | None, list[dict]] = {}
        for t in self._traces:
            if context is not None and t.context != context:
                continue
            tree.setdefault(t.context, []).append(
                {
                    "expr": t.expr_s,
                    "result": t.result_s,
                    "depth": t.depth,
                }
            )
        return tree
