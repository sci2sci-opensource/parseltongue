from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypedDict

from parseltongue.core.atoms import Axiom, Symbol, Term, Theorem
from parseltongue.core.engine import Engine, Fact
from parseltongue.core.lang import Sentence


class _GraphEntry(TypedDict, total=False):
    kind: NodeKind
    value: Sentence
    inputs: list[str]
    atom: Fact | Axiom | Theorem | Term | None
    _trace: Any


if TYPE_CHECKING:
    from parseltongue.core.loader.lazy_loader import LazyLoadResult

    from .vital.stain import Stain
    from .vital.tracer import Tracer


class NodeKind(StrEnum):
    FACT = "fact"
    AXIOM = "axiom"
    THEOREM = "theorem"
    CALC = "calc"
    TERM_FWD = "term-fwd"
    TERM_COMP = "term-comp"
    DIFF = "diff"
    SYNTHETIC = "synthetic"


class InputType(StrEnum):
    DECLARE = "declare"
    USE = "use"
    PULL = "pull"


@dataclass
class Node:
    name: str
    kind: NodeKind
    value: Any = None
    inputs: list = field(default_factory=list)
    atom: Fact | Axiom | Theorem | Term | None = None


@dataclass
class ConsumerInput:
    name: str
    input_type: InputType
    source_depth: int = 0  # for using_refs: depth of the referenced node


@dataclass
class Consumer:
    node: Node
    uses: list = field(default_factory=list)  # list of ConsumerInput (USE — from bar)
    declares: list = field(default_factory=list)  # list of ConsumerInput (DECLARE — inline facts)
    pulls: list = field(default_factory=list)  # list of ConsumerInput (PULL — from deeper result)

    @property
    def name(self) -> str:
        return self.node.name

    @property
    def kind(self) -> NodeKind:
        return self.node.kind

    @property
    def value(self):
        return self.node.value


@dataclass
class Layer:
    depth: int
    consumers: list = field(default_factory=list)  # list of Consumer


@dataclass
class CoreToConsequenceStructure:
    layers: list = field(default_factory=list)  # list of Layer (layer 0 = roots)
    graph: dict[str, Node] = field(default_factory=dict)
    depths: dict[str, int] = field(default_factory=dict)
    max_depth: int = 0

    @property
    def roots(self) -> Layer | None:
        """Layer 0 — root declarations (axioms, forward terms)."""
        return self.layers[0] if self.layers and self.layers[0].depth == 0 else None

    @property
    def root_names(self) -> set:
        """Names of all root nodes."""
        r = self.roots
        return {c.name for c in r.consumers} if r else set()

    def localize(self, name: str) -> "CoreToConsequenceStructure":
        """Localize the structure around a single consumer: its upstream and its downstream chain."""
        # Index: who pulls from whom
        pulled_by: dict[str, set[str]] = {}  # name -> set of consumer names that pull from it
        consumer_by_name = {}  # name -> Consumer
        for layer in self.layers:
            for c in layer.consumers:
                consumer_by_name[c.name] = c
                for p in c.pulls:
                    pulled_by.setdefault(p.name, set()).add(c.name)

        # Index: which axioms are attached to which term-fwd via wff references
        axiom_for_term: dict[str, list[str]] = {}  # term-fwd name -> [axiom names]
        for n, node in self.graph.items():
            if node.kind == NodeKind.AXIOM and node.atom is not None and hasattr(node.atom, "wff"):
                for ref in _collect_symbols(node.atom.wff):
                    if ref in self.graph and self.graph[ref].kind == NodeKind.TERM_FWD:
                        axiom_for_term.setdefault(ref, []).append(n)

        # Phase 1: backward from seed — full upstream trace
        upstream = {name}
        back_queue = [name]
        while back_queue:
            current = back_queue.pop()
            c = consumer_by_name.get(current)
            if c:
                for inp in c.uses + c.declares + c.pulls:
                    if inp.name not in upstream:
                        upstream.add(inp.name)
                        back_queue.append(inp.name)
            # term-fwd: include attached axioms (rewrite rules)
            for ax in axiom_for_term.get(current, []):
                if ax not in upstream:
                    upstream.add(ax)
                    back_queue.append(ax)

        # Phase 2: forward from seed — only follow pulls, don't backtrack
        forward = set()
        fwd_queue = [name]
        while fwd_queue:
            current = fwd_queue.pop()
            for dependent in pulled_by.get(current, set()):
                if dependent not in forward:
                    forward.add(dependent)
                    fwd_queue.append(dependent)

        included = upstream | forward

        # Build layers — forward consumers get trimmed (only chain-connected pulls/uses)
        new_layers = []
        for layer in self.layers:
            filtered = []
            for c in layer.consumers:
                if c.name not in included:
                    continue
                if c.name in forward and c.name not in upstream:
                    # Forward-only consumer: keep declares, filter pulls/uses to chain
                    trimmed = Consumer(
                        node=c.node,
                        uses=[u for u in c.uses if u.name in included],
                        declares=c.declares,
                        pulls=[p for p in c.pulls if p.name in included],
                    )
                    filtered.append(trimmed)
                else:
                    filtered.append(c)
            new_layers.append(Layer(depth=layer.depth, consumers=filtered))

        # Collect all names referenced by included consumers (for graph/depths)
        all_names = set()
        for layer in new_layers:
            for c in layer.consumers:
                all_names.add(c.name)
                for inp in c.uses + c.declares + c.pulls:
                    all_names.add(inp.name)

        new_graph = {n: node for n, node in self.graph.items() if n in all_names}
        new_depths = {n: d for n, d in self.depths.items() if n in all_names}
        new_max = max(new_depths.values()) if new_depths else 0

        return CoreToConsequenceStructure(
            layers=new_layers,
            graph=new_graph,
            depths=new_depths,
            max_depth=new_max,
        )

    @property
    def last_root_use_depth(self) -> int:
        """Deepest layer that still references a root via :using."""
        return max(
            (
                layer.depth
                for layer in self.layers
                if layer.depth > 0 and any(inp for c in layer.consumers for inp in c.uses)
            ),
            default=0,
        )


# ── Shared primitives ──


def _collect_symbols(expr) -> set[str]:
    """Extract all Symbol names from an s-expression tree."""
    if isinstance(expr, Symbol):
        return {str(expr)}
    if isinstance(expr, list):
        r: set[str] = set()
        for item in expr:
            r |= _collect_symbols(item)
        return r
    return set()


def _walk_engine(name: str, engine: Engine, graph: dict[str, _GraphEntry], visited: set[str]) -> None:
    """Walk a single name through the engine, populating *graph* in place."""
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
            _walk_engine(dep, engine, graph, visited)
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
                _walk_engine(dep, engine, graph, visited)
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


def _augment_with_stain(
    graph: dict[str, _GraphEntry],
    stain: "Stain | Tracer",
    visited: set[str],
    engine: Engine,
    store: str | int = "names",
) -> int:
    """Augment *graph* with runtime edges from a Stain or Tracer.

    Returns the number of new edges added.
    """
    stain_edges = stain.edge_dict()
    added = 0

    for caller, callees in stain_edges.items():
        if caller not in graph:
            _walk_engine(caller, engine, graph, visited)
        if caller not in graph:
            continue
        for callee in callees:
            if callee not in graph:
                _walk_engine(callee, engine, graph, visited)
            if callee not in graph:
                continue
            if callee not in graph[caller]["inputs"]:
                graph[caller]["inputs"].append(callee)
                added += 1

    # Anonymous trace nodes
    if store != "names" and stain.traces:
        from .vital.stain import Trace

        def _include_trace(t: Trace) -> bool:
            if store == "all":
                return True
            if store == "heads":
                return t.expr_s.startswith("(")
            if isinstance(store, int):
                return t.depth <= store
            return False

        ctx_counters: dict[str | None, int] = {}
        for trace in stain.traces:
            if not _include_trace(trace):
                continue
            if trace.context is None or trace.context not in graph:
                continue
            if trace.expr_s == trace.context:
                continue

            idx = ctx_counters.get(trace.context, 0)
            ctx_counters[trace.context] = idx + 1
            anon_name = f"{trace.context}#{idx}"

            graph[anon_name] = {
                "kind": NodeKind.TERM_COMP,
                "value": trace.result_s,
                "inputs": [],
                "atom": None,
                "_trace": trace,
            }
            if anon_name not in graph[trace.context]["inputs"]:
                graph[trace.context]["inputs"].append(anon_name)
                added += 1

    return added


def _compute_depths(graph: dict[str, _GraphEntry]) -> dict[str, int]:
    """Compute node depths from a populated graph dict."""
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

    return memo


def _graph_to_structure(graph: dict[str, _GraphEntry], engine: Engine) -> CoreToConsequenceStructure:
    """Convert a populated graph dict into a layered CoreToConsequenceStructure."""
    if not graph:
        return CoreToConsequenceStructure()

    depths = _compute_depths(graph)
    max_depth = max(depths.values()) if depths else 0

    # Consumed-at tracking & root detection
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

    root_groups: list[list[str]] = []
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

    # Build Node objects
    nodes: dict[str, Node] = {}
    for name, data in graph.items():
        nodes[name] = Node(
            name=name, kind=data["kind"], value=data["value"], inputs=list(data["inputs"]), atom=data.get("atom")
        )

    # Build layers
    by_depth: dict[int, list[str]] = {}
    for n in graph:
        by_depth.setdefault(depths[n], []).append(n)

    theorem_order = {name: i for i, name in enumerate(engine.theorems)}
    for d in by_depth:
        if d > 0:
            by_depth[d].sort(key=lambda n: theorem_order.get(n, 999))

    layers = []

    layer0 = Layer(depth=0)
    for group in root_groups:
        for name in group:
            layer0.consumers.append(Consumer(node=nodes[name]))
    layers.append(layer0)

    for d in range(1, max_depth + 1):
        consumer_names = by_depth.get(d, [])
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

            layer.consumers.append(Consumer(node=nodes[cname], uses=uses, declares=declares, pulls=pulls))
        layers.append(layer)

    return CoreToConsequenceStructure(layers=layers, graph=nodes, depths=dict(depths), max_depth=max_depth)


# ── Public probes ──


def probe(term: str | list[str], engine: Engine) -> CoreToConsequenceStructure:
    """Static probe — walk named terms through the engine graph."""
    graph: dict[str, _GraphEntry] = {}
    terms = [term] if isinstance(term, str) else term
    visited: set[str] = set()
    for t in terms:
        _walk_engine(t, engine, graph, visited)

    graph["__output__"] = {
        "kind": NodeKind.SYNTHETIC,
        "value": "",
        "inputs": [t for t in terms if t in graph],
    }

    return _graph_to_structure(graph, engine)


def probe_all(result: "LazyLoadResult") -> CoreToConsequenceStructure:
    """Probe the full engine from a LazyLoadResult.

    Uses result.roots() to find unreferenced names, then walks their
    full dependency graphs into a single merged structure.
    """
    roots = result.roots()
    if not roots:
        return CoreToConsequenceStructure(layers=[], graph={}, depths={}, max_depth=0)
    return probe(roots, result.system.engine)


@dataclass
class DiffMeta:
    """Lightweight metadata for one engine diff — no evaluation."""

    name: str
    replace: str
    with_: str
    replace_kind: str  # NodeKind value or "unknown"
    with_kind: str
    source_file: str
    source_line: int


def _resolve_kind(name: str, engine: Engine) -> str:
    """Resolve the kind of a name without evaluating anything."""
    if name in engine.facts:
        return NodeKind.FACT
    if name in engine.axioms:
        return NodeKind.AXIOM
    if name in engine.theorems:
        return NodeKind.THEOREM
    if name in engine.terms:
        t = engine.terms[name]
        return NodeKind.TERM_COMP if t.definition is not None else NodeKind.TERM_FWD
    return "unknown"


def probe_diffs(result: "LazyLoadResult") -> list[DiffMeta]:
    """Walk the AST for diff directives and collect metadata.

    Pulls source_file:source_line from DirectiveNodes in result.loaded,
    resolves replace/with kinds from the engine. No diff evaluation.
    """
    engine = result.system.engine
    if not hasattr(engine, "diffs"):
        return []

    # Index AST diff nodes by name for source locations
    diff_nodes = {}
    for node in result.loaded:
        if node.kind == "diff" and node.name:
            diff_nodes[node.name] = node

    results = []
    for name, diff in engine.diffs.items():
        ast_node = diff_nodes.get(name)
        results.append(
            DiffMeta(
                name=name,
                replace=diff.get("replace", ""),
                with_=diff.get("with", ""),
                replace_kind=_resolve_kind(diff.get("replace", ""), engine),
                with_kind=_resolve_kind(diff.get("with", ""), engine),
                source_file=ast_node.source_file if ast_node else "",
                source_line=ast_node.source_line if ast_node else 0,
            )
        )
    return results
