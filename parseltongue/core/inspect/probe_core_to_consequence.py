from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from parseltongue.core.atoms import Axiom, Term, Theorem
from parseltongue.core.engine import Engine, Fact

if TYPE_CHECKING:
    from parseltongue.core.loader.lazy_loader import LazyLoadResult


class NodeKind(StrEnum):
    FACT = "fact"
    AXIOM = "axiom"
    THEOREM = "theorem"
    CALC = "calc"
    TERM_FWD = "term-fwd"
    TERM_COMP = "term-comp"
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
    graph: dict = field(default_factory=dict)  # name -> Node
    depths: dict = field(default_factory=dict)  # name -> int
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
        from parseltongue.core.atoms import Symbol as _Sym

        def _syms(expr):
            if isinstance(expr, _Sym):
                return {str(expr)}
            if isinstance(expr, list):
                r = set()
                for item in expr:
                    r |= _syms(item)
                return r
            return set()

        axiom_for_term: dict[str, list[str]] = {}  # term-fwd name -> [axiom names]
        for n, node in self.graph.items():
            if node.kind == NodeKind.AXIOM and node.atom is not None:
                for ref in _syms(node.atom.wff):
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


def probe(term: str | list[str], engine: Engine) -> CoreToConsequenceStructure:
    from parseltongue.core.atoms import Symbol
    from parseltongue.core.lang import to_sexp

    def _fmt_value(v):
        if isinstance(v, (list, Symbol)):
            return to_sexp(v)
        return repr(v)

    def _collect_symbols(expr):
        if isinstance(expr, Symbol):
            return {str(expr)}
        if isinstance(expr, list):
            r = set()
            for item in expr:
                r |= _collect_symbols(item)
            return r
        return set()

    # --- Build dependency graph from engine ---
    graph = {}

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

    graph["__output__"] = {
        "kind": NodeKind.SYNTHETIC,
        "value": "",
        "inputs": [t for t in terms if t in graph],
    }

    # --- Depth computation ---
    def compute_depths(g):
        memo: dict[str, int] = {}

        def depth(n):
            if n in memo:
                return memo[n]
            if not g[n]["inputs"]:
                memo[n] = 0
            else:
                memo[n] = 1 + max(depth(i) for i in g[n]["inputs"] if i in g)
            return memo[n]

        for n in g:
            depth(n)

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
                    facts = frozenset(i for i in g[n]["inputs"] if i in g and g[i]["kind"] == NodeKind.FACT)
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
                inputs_in_g = [i for i in g[n]["inputs"] if i in g]
                if inputs_in_g:
                    min_depth = 1 + max(memo[i] for i in inputs_in_g)
                    if memo[n] < min_depth:
                        memo[n] = min_depth
                        settled = False
        return memo

    depths = compute_depths(graph)
    max_depth = max(depths.values())

    # --- Consumed-at tracking & root detection ---
    consumed_at: dict[str, set[int]] = {n: set() for n in graph}
    for n in graph:
        for inp in graph[n]["inputs"]:
            if inp in graph:
                consumed_at[inp].add(depths[n])

    # Roots: axioms/forward terms always, term-comp if consumed at multiple depths
    root_set = {
        n
        for n in graph
        if (len(consumed_at[n]) > 1 and graph[n]["kind"] in (NodeKind.AXIOM, NodeKind.TERM_COMP, NodeKind.TERM_FWD))
        or graph[n]["kind"] in (NodeKind.AXIOM, NodeKind.TERM_FWD)
    }

    # Group roots by (depth, consumed_at) for ordering
    root_groups = []
    assigned = set()
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

    # Group primaries are the visible :using targets; secondaries are implicit
    root_primaries = {g[0] for g in root_groups}

    # --- Build Node objects ---
    nodes = {}
    for name, data in graph.items():
        nodes[name] = Node(
            name=name, kind=data["kind"], value=data["value"], inputs=list(data["inputs"]), atom=data.get("atom")
        )

    # --- Build layers ---
    by_depth: dict[int, list[str]] = {}
    for n in graph:
        by_depth.setdefault(depths[n], []).append(n)

    theorem_order = {name: i for i, name in enumerate(engine.theorems)}
    for d in by_depth:
        if d > 0:
            by_depth[d].sort(key=lambda n: theorem_order.get(n, 999))

    layers = []

    # Layer 0: roots, ordered by group
    layer0 = Layer(depth=0)
    for group in root_groups:
        for name in group:
            cnode = graph[name]
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


def probe_all(result: "LazyLoadResult") -> CoreToConsequenceStructure:
    """Probe the full engine from a LazyLoadResult.

    Uses result.roots() to find unreferenced names, then walks their
    full dependency graphs into a single merged structure.
    """
    roots = result.roots()
    if not roots:
        return CoreToConsequenceStructure(layers=[], graph={}, depths={}, max_depth=0)
    return probe(roots, result.system.engine)
