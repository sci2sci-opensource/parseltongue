"""Live probe — augments static probe with runtime edges.

Builds the same CoreToConsequenceStructure as the static probe, but
with additional inputs discovered during engine evaluation.

Accepts either a Stain (old recursive engine) or a Tracer (stack engine).
Detection is automatic via ``Tracer.supported(engine)``.

Usage with Tracer (stack engine)::

    from parseltongue.core.inspect.vital import Tracer, live_probe

    tracer = Tracer(engine)
    tracer.express()
    # ... engine evaluates ...
    tracer.suppress()
    structure = live_probe("checker.policy-consistent", engine, tracer)

Usage with Stain (recursive engine)::

    from parseltongue.core.inspect.vital import Stain, live_probe

    with Stain(engine, capture="all") as stain:
        # ... engine evaluates ...
    structure = live_probe("checker.policy-consistent", engine, stain, store="all")
"""

from __future__ import annotations

import logging

from parseltongue.core.atoms import Symbol

from ..probe_core_to_consequence import (
    CoreToConsequenceStructure,
    NodeKind,
    _augment_with_stain,
    _graph_to_structure,
    _GraphEntry,
    _walk_engine,
)
from .stain import Stain
from .tracer import Tracer

log = logging.getLogger("parseltongue.vital.live_probe")


def trace_engine(engine, names: list[str] | None = None, capture: str | int = "names") -> Stain | Tracer:
    """Evaluate theorems under tracing — returns a Stain or Tracer with captured edges.

    Detects engine type automatically:
    - Stack engine (has _tracing): uses Tracer (express/suppress)
    - Recursive engine: uses Stain (apply/remove with push_context)

    Parameters:
        engine: The engine to trace.
        names: Theorem names to evaluate. None = all theorems.
        capture: Capture mode (only affects Stain; Tracer always captures edges).
    """
    theorem_names = names if names is not None else list(engine.theorems.keys())

    if Tracer.supported(engine):
        tracer = Tracer(engine)
        tracer.express()
        for tname in theorem_names:
            if tname in engine.theorems:
                try:
                    engine.evaluate(Symbol(tname))
                except Exception:
                    pass
        tracer.suppress()
        return tracer
    else:
        stain_obj = Stain(engine, capture=capture)
        stain_obj.apply()
        for tname in theorem_names:
            if tname in engine.theorems and engine.theorems[tname].wff is not None:
                stain_obj.push_context(tname)
                try:
                    engine.evaluate(engine.theorems[tname].wff)
                except Exception:
                    pass
                stain_obj.pop_context()
        stain_obj.remove()
        return stain_obj


def live_probe(
    term: str | list[str],
    engine,
    stain: Stain | Tracer | None = None,
    store: str | int = "names",
) -> CoreToConsequenceStructure:
    """Probe with runtime edges from a Stain or Tracer.

    If stain is None, traces the engine automatically via trace_engine().

    Parameters:
        term: Root term(s) to probe.
        engine: The engine to probe.
        stain: A Stain or Tracer with captured edges, or None to auto-trace.
        store: Controls anonymous node inclusion:
            "names" — only named entities (default)
            "heads" — named + expression heads from traces
            "all"   — every trace entry becomes a node
            int N   — traces up to N call levels from named context
    """
    if stain is None:
        stain = trace_engine(engine)

    # Phase 1: Build static graph
    graph: dict[str, _GraphEntry] = {}
    terms = [term] if isinstance(term, str) else term
    visited: set[str] = set()
    for t in terms:
        _walk_engine(t, engine, graph, visited)

    # Phase 2: Augment with stain edges
    added = _augment_with_stain(graph, stain, visited, engine, store)
    log.info("Live probe: %d stain edges augmented graph (%d new)", len(stain.edges), added)

    # Phase 3: Synthetic output node
    graph["__output__"] = {
        "kind": NodeKind.SYNTHETIC,
        "value": "",
        "inputs": [t for t in terms if t in graph],
    }

    return _graph_to_structure(graph, engine)


def probe_diffs_to_possibilities(
    engine,
    stain: Stain | Tracer | None = None,
    store: str | int = "names",
) -> CoreToConsequenceStructure:
    """Probe all diffs — walk both sides, splice into unified structure with DIFF nodes.

    Diffs are fundamentally live: each side may reference dynamic terms that
    only resolve at runtime.  If *stain* is None the engine is auto-traced
    via :func:`trace_engine`.

    Parameters:
        engine: The engine whose diffs to probe.
        stain: A Stain or Tracer with captured edges, or None to auto-trace.
        store: Controls anonymous node inclusion (same semantics as live_probe).
    """
    if not engine.diffs:
        return CoreToConsequenceStructure()

    # Auto-trace — diffs are live by nature
    if stain is None:
        stain = trace_engine(engine)

    graph: dict[str, _GraphEntry] = {}
    visited: set[str] = set()

    # Walk both sides of every diff
    for diff_name, diff in engine.diffs.items():
        _walk_engine(diff["replace"], engine, graph, visited)
        _walk_engine(diff["with"], engine, graph, visited)

    # Augment with runtime edges
    _augment_with_stain(graph, stain, visited, engine, store)

    # Insert DIFF nodes — each diff becomes a node whose inputs are its two sides
    for diff_name, diff in engine.diffs.items():
        dr = engine.eval_diff(diff_name)
        inputs = [s for s in [diff["replace"], diff["with"]] if s in graph]
        graph[diff_name] = {
            "kind": NodeKind.DIFF,
            "value": dr.to_dict(),
            "inputs": inputs,
        }

    # Synthetic output collecting all diff nodes
    graph["__output__"] = {
        "kind": NodeKind.SYNTHETIC,
        "value": "",
        "inputs": [n for n in engine.diffs if n in graph],
    }

    return _graph_to_structure(graph, engine)
