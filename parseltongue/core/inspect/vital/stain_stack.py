"""Stain — instruments an engine to capture runtime dependency edges.

Works with the iterative (stack-based) engine via ``engine._eval_observer``.

Context tracking derives the current named entity from the engine's own
continuation stack: scan frames for the nearest _K_ARGS whose head is a
known term/theorem.  No separate context stack or watermarks needed for
auto-tracked contexts.

For _rewrite: still monkey-patches since _rewrite is called normally
from inside the iterative loop.

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

# Continuation tags (must match engine_stack.py)
_K_ARGS = 0
_K_CONTEXT = 9


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

    Uses the observer hook for iterative engines and monkey-patches
    _rewrite for axiom tracking.  Non-destructive: remove() restores.

    Context is derived from two sources (checked in order):
    1. Manual context stack (push_context/pop_context) — for derive etc.
    2. Engine continuation stack — scan _K_ARGS frames for nearest named head.

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
        self._original_rewrite = None
        self._original_observer = None
        self._edges: set[Edge] = set()
        self._traces: list[Trace] = []
        self._manual_context: list[str] = []  # push_context / pop_context
        self._applied = False
        self._capture = capture
        self._pending_trace_idx: int = -1  # index of trace awaiting result
        self._current_context: str | None = None  # cached for _rewrite

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

    def _context_from_stack(self, stack) -> tuple[str | None, int]:
        """Derive context from engine stack + manual context.

        Returns (context_name, depth_from_context).

        The engine pushes _K_CONTEXT marker frames when a Symbol resolves
        to a term/theorem via tail-call.  Scan top-down for the nearest one.
        Manual context (push_context) takes priority.
        """
        stack_depth = len(stack)

        if self._manual_context:
            return self._manual_context[-1], stack_depth

        # Scan stack top-down for nearest _K_CONTEXT marker
        for i in range(stack_depth - 1, -1, -1):
            frame = stack[i]
            if isinstance(frame, tuple) and len(frame) == 2 and frame[0] == _K_CONTEXT:
                return frame[1], stack_depth - i

        return None, 0

    def _observer(self, expr, result, stack):
        """Observer callback — called on every step of the iterative _eval.

        Called twice per expression:
          pre-step:  result is None  — expression about to be evaluated
          post-step: result is not None — expression just evaluated
        """
        engine = self._engine
        stack_depth = len(stack)

        # ── POST-STEP: fill in trace result ──
        if result is not None:
            if self._pending_trace_idx >= 0:
                old = self._traces[self._pending_trace_idx]
                self._traces[self._pending_trace_idx] = Trace(
                    context=old.context,
                    expr_s=old.expr_s,
                    result_s=_truncate_sexp(result),
                    depth=old.depth,
                )
                self._pending_trace_idx = -1
            return

        # ── PRE-STEP ──

        context, ctx_depth = self._context_from_stack(stack)
        self._current_context = context  # cache for _rewrite
        trace_this = False

        if isinstance(expr, Symbol):
            name = str(expr)

            # Record resolve edge
            if name in engine.terms:
                if context and context != name:
                    self._edges.add(Edge(context, name, "resolve"))
            elif name in engine.theorems:
                if context and context != name:
                    self._edges.add(Edge(context, name, "resolve"))
            elif name in engine.facts:
                if context and context != name:
                    self._edges.add(Edge(context, name, "resolve"))

            trace_this = self._should_trace(ctx_depth)

        elif isinstance(expr, (list, tuple)) and expr:
            head = expr[0]
            if isinstance(head, Symbol):
                head_name = str(head)
                if context and context != head_name:
                    if head_name in engine.terms:
                        self._edges.add(Edge(context, head_name, "effect"))
                        self._edges.add(Edge(context, head_name, "resolve"))
                    elif head_name in engine.theorems:
                        self._edges.add(Edge(context, head_name, "resolve"))
                    elif head_name in engine.facts:
                        self._edges.add(Edge(context, head_name, "resolve"))
                    for arg in expr[1:]:
                        if isinstance(arg, Symbol):
                            arg_name = str(arg)
                            if arg_name in engine.facts or arg_name in engine.terms or arg_name in engine.theorems:
                                self._edges.add(Edge(context, arg_name, "resolve"))

            if self._capture == "heads":
                trace_this = isinstance(expr, (list, tuple)) and bool(expr)
            else:
                trace_this = self._should_trace(ctx_depth)

        elif self._capture not in ("names", "heads"):
            trace_this = self._should_trace(ctx_depth)

        # Record trace placeholder
        if trace_this:
            self._pending_trace_idx = len(self._traces)
            self._traces.append(
                Trace(
                    context=context,
                    expr_s=_truncate_sexp(expr),
                    result_s="",
                    depth=ctx_depth,
                )
            )

    def apply(self) -> "Stain":
        """Apply the stain — start recording. Returns self for chaining."""
        if self._applied:
            return self
        engine = self._engine
        stain = self

        # ── Set up observer for _eval tracking ──
        self._original_observer = engine._eval_observer

        def _combined_observer(expr, result, stack):
            stain._observer(expr, result, stack)
            if stain._original_observer:
                stain._original_observer(expr, result, stack)

        engine._eval_observer = _combined_observer

        # ── Stained _rewrite (still monkey-patched — called normally) ──
        self._original_rewrite = engine._rewrite

        def _stained_rewrite(expr, depth=0, axiom_scope=None, _prev=None):
            context = stain._current_context

            result = stain._original_rewrite(expr, depth, axiom_scope, _prev)

            if result != expr and context:
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
                        for var, val in bindings.items():
                            if isinstance(val, Symbol):
                                val_name = str(val)
                                if val_name in engine.facts:
                                    stain._edges.add(Edge(context, val_name, "resolve"))
                                elif val_name in engine.terms:
                                    stain._edges.add(Edge(context, val_name, "resolve"))
                        break

            return result

        engine._rewrite = _stained_rewrite
        self._applied = True
        log.info("Stain applied to engine (capture=%s)", self._capture)
        return self

    def remove(self) -> "Stain":
        """Remove the stain — restore originals."""
        if self._applied:
            self._engine._eval_observer = self._original_observer
            self._original_observer = None
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
        self._manual_context.clear()
        self._pending_trace_idx = -1
        self._current_context = None
        return self

    def push_context(self, name: str):
        """Manually push an evaluation context (e.g. for a derive being evaluated)."""
        self._manual_context.append(name)

    def pop_context(self):
        """Pop the current evaluation context."""
        if self._manual_context:
            self._manual_context.pop()

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
