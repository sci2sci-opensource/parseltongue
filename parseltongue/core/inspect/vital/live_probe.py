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
from parseltongue.core.lang import to_sexp

from ..probe_core_to_consequence import (
    Consumer,
    ConsumerInput,
    CoreToConsequenceStructure,
    InputType,
    Layer,
    Node,
    NodeKind,
    _GraphEntry,
)
from .stain import Stain, Trace
from .tracer import Tracer

log = logging.getLogger("parseltongue.vital.live_probe")


def _collect_symbols(expr) -> set[str]:
    if isinstance(expr, Symbol):
        return {str(expr)}
    if isinstance(expr, list):
        r: set[str] = set()
        for item in expr:
            r |= _collect_symbols(item)
        return r
    return set()


def _fmt_value(v):
    if isinstance(v, (list, Symbol)):
        return to_sexp(v)
    return repr(v)


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

    # --- Phase 1: Build static graph (same as probe.walk) ---
    graph: dict[str, _GraphEntry] = {}

    def walk(name, visited=None):
        if visited is None:
            visited = set()
        if name in visited or name in graph:
            return
        visited.add(name)
        if name in engine.theorems:
            thm = engine.theorems[name]
            try:
                val = engine.evaluate(thm.wff)
            except Exception:
                val = thm.wff
            has_bind = any(d in engine.axioms for d in thm.derivation)
            graph[name] = {
                "kind": NodeKind.THEOREM if has_bind else NodeKind.CALC,
                "value": val,
                "inputs": list(thm.derivation),
                "atom": thm,
            }
            for dep in thm.derivation:
                walk(dep, visited)
        elif name in engine.terms:
            t = engine.terms[name]
            if t.definition is not None:
                try:
                    val = engine.evaluate(t.definition)
                except Exception:
                    val = t.definition
                deps = sorted(
                    d
                    for d in _collect_symbols(t.definition)
                    if d in engine.facts or d in engine.terms or d in engine.theorems or d in engine.axioms
                )
                graph[name] = {"kind": NodeKind.TERM_COMP, "value": val, "inputs": deps, "atom": t}
                for dep in deps:
                    walk(dep, visited)
            else:
                graph[name] = {"kind": NodeKind.TERM_FWD, "value": "", "inputs": [], "atom": t}
        elif name in engine.facts:
            graph[name] = {
                "kind": NodeKind.FACT,
                "value": engine.facts[name].wff,
                "inputs": [],
                "atom": engine.facts[name],
            }
        elif name in engine.axioms:
            graph[name] = {
                "kind": NodeKind.AXIOM,
                "value": engine.axioms[name].wff,
                "inputs": [],
                "atom": engine.axioms[name],
            }

    terms = [term] if isinstance(term, str) else term
    visited: set[str] = set()
    for t in terms:
        walk(t, visited)

    # --- Phase 2: Augment with stain edges ---
    stain_edges = stain.edge_dict()
    added_edges = 0

    for caller, callees in stain_edges.items():
        if caller not in graph:
            walk(caller, visited)
        if caller not in graph:
            continue

        for callee in callees:
            if callee not in graph:
                walk(callee, visited)
            if callee not in graph:
                continue

            if callee not in graph[caller]["inputs"]:
                graph[caller]["inputs"].append(callee)
                added_edges += 1

    log.info("Live probe: %d stain edges augmented graph (%d new)", len(stain.edges), added_edges)

    # --- Phase 2b: Augment with trace entries (anonymous nodes) ---
    added_traces = 0
    if store != "names" and stain.traces:
        # Filter traces based on store parameter
        def _include_trace(t: Trace) -> bool:
            if store == "all":
                return True
            if store == "heads":
                # Only list expressions (heads)
                return t.expr_s.startswith("(")
            if isinstance(store, int):
                return t.depth <= store
            return False

        # Group traces by context, create anonymous nodes
        # Anonymous node name = context + "#" + index (unique within context)
        ctx_counters: dict[str | None, int] = {}
        for trace in stain.traces:
            if not _include_trace(trace):
                continue
            if trace.context is None:
                continue
            if trace.context not in graph:
                continue

            # Create a unique name for this anonymous node
            idx = ctx_counters.get(trace.context, 0)
            ctx_counters[trace.context] = idx + 1
            anon_name = f"{trace.context}#{idx}"

            # Skip if the expression is just the context itself (self-reference)
            if trace.expr_s == trace.context:
                continue

            # Create anonymous node
            graph[anon_name] = {
                "kind": NodeKind.TERM_COMP,  # anonymous expressions are computed
                "value": trace.result_s,
                "inputs": [],
                "atom": None,
                "_trace": trace,  # attach trace for inspection
            }

            # Wire: context → anon_name
            if anon_name not in graph[trace.context]["inputs"]:
                graph[trace.context]["inputs"].append(anon_name)
                added_traces += 1

        log.info("Live probe: %d anonymous trace nodes added (store=%s)", added_traces, store)

    # --- Phase 3: Synthetic output node ---
    graph["__output__"] = {
        "kind": NodeKind.SYNTHETIC,
        "value": "",
        "inputs": [t for t in terms if t in graph],
    }

    # --- Phase 4: Depth computation (same as static probe) ---
    memo: dict[str, int] = {}

    for start in graph:
        if start in memo:
            continue
        stack = [(start, False)]
        while stack:
            n, children_done = stack[-1]
            if n in memo:
                stack.pop()
                continue
            inputs = [i for i in graph[n]["inputs"] if i in graph]
            if not inputs:
                memo[n] = 0
                stack.pop()
                continue
            if children_done:
                memo[n] = 1 + max(memo.get(i, 0) for i in inputs)
                stack.pop()
            else:
                stack[-1] = (n, True)
                for i in reversed(inputs):
                    if i not in memo:
                        stack.append((i, False))

    # Layout: bump consumers whose fact set subsumes a sibling's
    changed = True
    while changed:
        changed = False
        by_d: dict[int, list[str]] = {}
        for n, d in memo.items():
            if d > 0:
                by_d.setdefault(d, []).append(n)
        for d, nodes in by_d.items():
            if len(nodes) < 2:
                continue
            fact_sets = {}
            for n in nodes:
                facts = frozenset(i for i in graph[n]["inputs"] if i in graph and graph[i]["kind"] == NodeKind.FACT)
                fact_sets[n] = facts
            for n in nodes:
                for other in nodes:
                    if n != other and fact_sets[n] > fact_sets[other]:
                        memo[n] = d + 1
                        changed = True
                        break
                if changed:
                    break

    # Ensure all depths respect input ordering
    settled = False
    while not settled:
        settled = True
        for n in memo:
            inputs_in_g = [i for i in graph[n]["inputs"] if i in graph]
            if inputs_in_g:
                min_depth = 1 + max(memo[i] for i in inputs_in_g)
                if memo[n] < min_depth:
                    memo[n] = min_depth
                    settled = False

    depths = memo
    max_depth = max(depths.values()) if depths else 0

    # --- Phase 5: Consumed-at tracking & root detection ---
    consumed_at: dict[str, set[int]] = {n: set() for n in graph}
    for n in graph:
        for inp in graph[n]["inputs"]:
            if inp in graph:
                consumed_at[inp].add(depths[n])

    root_set = {
        n
        for n in graph
        if (len(consumed_at[n]) > 1 and graph[n]["kind"] in (NodeKind.AXIOM, NodeKind.TERM_COMP, NodeKind.TERM_FWD))
        or graph[n]["kind"] in (NodeKind.AXIOM, NodeKind.TERM_FWD)
    }

    root_groups = []
    assigned: set[str] = set()
    for bn in sorted(root_set, key=lambda n: (depths[n], n)):
        if bn in assigned:
            continue
        group = [bn]
        assigned.add(bn)
        for other in sorted(root_set):
            if other not in assigned and depths[other] == depths[bn] and consumed_at[other] == consumed_at[bn]:
                group.append(other)
                assigned.add(other)
        root_groups.append(group)

    root_primaries = {g[0] for g in root_groups}

    # --- Phase 6: Build Node objects ---
    nodes = {}
    for name, data in graph.items():
        nodes[name] = Node(
            name=name, kind=data["kind"], value=data["value"], inputs=list(data["inputs"]), atom=data.get("atom")
        )

    # --- Phase 7: Build layers ---
    by_depth: dict[int, list[str]] = {}
    for n in graph:
        by_depth.setdefault(depths[n], []).append(n)

    theorem_order = {name: i for i, name in enumerate(engine.theorems)}
    for d in by_depth:
        if d > 0:
            by_depth[d].sort(key=lambda n: theorem_order.get(n, 999))

    layers = []

    # Layer 0: roots
    layer0 = Layer(depth=0)
    for group in root_groups:
        for name in group:
            layer0.consumers.append(Consumer(node=nodes[name]))
    layers.append(layer0)

    # Layers 1..max_depth
    for d in range(1, max_depth + 1):
        consumer_names = [n for n in by_depth.get(d, [])]
        if not consumer_names:
            continue

        layer = Layer(depth=d)
        for cname in consumer_names:
            cnode = graph[cname]

            uses = [ConsumerInput(name=i, input_type=InputType.USE) for i in cnode["inputs"] if i in root_primaries]
            declares = [
                ConsumerInput(name=i, input_type=InputType.DECLARE)
                for i in cnode["inputs"]
                if i not in root_set and depths.get(i, 0) == 0 and graph.get(i, {}).get("kind") == NodeKind.FACT
            ]
            pulls = [
                ConsumerInput(name=i, input_type=InputType.PULL, source_depth=depths.get(i, 0))
                for i in cnode["inputs"]
                if i not in root_set
                and i not in [x.name for x in declares]
                and depths.get(i, 0) > 0
                and depths.get(i, 0) < d
            ]

            consumer = Consumer(
                node=nodes[cname],
                uses=uses,
                declares=declares,
                pulls=pulls,
            )
            layer.consumers.append(consumer)
        layers.append(layer)

    structure = CoreToConsequenceStructure(
        layers=layers,
        graph=nodes,
        depths=dict(depths),
        max_depth=max_depth,
    )
    return structure
