"""Lens — focused view into a single provenance structure with pluggable perspectives."""

from __future__ import annotations

from typing import TypeVar

from ..perspective import Perspective
from ..probe_core_to_consequence import (
    CoreToConsequenceStructure,
    InputType,
    Node,
    NodeKind,
)
from .base import Optics

T = TypeVar("T")


class Lens(Optics):
    """Single-structure optic. Views one provenance graph through perspectives."""

    def __init__(self, structure: CoreToConsequenceStructure, perspectives: list[Perspective] | None = None):
        self._structure = structure
        self._perspectives: dict[type[Perspective], Perspective] = {}
        for p in perspectives or []:
            self._perspectives[type(p)] = p
        self.__names: set[str] = set(structure.graph.keys()) - {"__output__"}

    @property
    def _names(self) -> set[str]:
        return self.__names

    def _get(self, perspective: type[Perspective[T]] | None = None) -> Perspective[T]:
        if perspective is None:
            return next(iter(self._perspectives.values()))
        inst = self._perspectives.get(perspective)
        if inst is None:
            available = [p.__name__ for p in self._perspectives]
            raise KeyError(f"Perspective {perspective.__name__!r} not registered. Available: {', '.join(available)}")
        return inst

    def _not_found(self, name: str) -> KeyError:
        suggestions = self.fuzzy(name)
        if suggestions:
            return KeyError(f"No {name!r}. Did you mean: {', '.join(suggestions)}")
        return KeyError(f"No {name!r}")

    def focus(self, name: str) -> "Lens":
        return Lens(self._structure.localize(name), list(self._perspectives.values()))

    def view(self, perspective: type[Perspective[T]] | None = None) -> T:
        return self._get(perspective).render_structure(self._structure)

    def view_layer(self, depth: int, perspective: type[Perspective[T]] | None = None) -> T:
        layer = next((ly for ly in self._structure.layers if ly.depth == depth), None)
        if layer is None:
            raise KeyError(f"No layer at depth {depth}")
        return self._get(perspective).render_layer(layer)

    def view_consumer(self, name: str, perspective: type[Perspective[T]] | None = None) -> T:
        p = self._get(perspective)
        for layer in self._structure.layers:
            for c in layer.consumers:
                if c.name == name:
                    return p.render_consumer(c)
        raise self._not_found(name)

    def view_node(self, name: str, perspective: type[Perspective[T]] | None = None) -> T:
        if name not in self._structure.graph:
            raise self._not_found(name)
        return self._get(perspective).render_node(self._structure.graph[name])

    def view_inputs(self, name: str, perspective: type[Perspective[T]] | None = None, *input_types: InputType) -> T:
        p = self._get(perspective)
        for layer in self._structure.layers:
            for c in layer.consumers:
                if c.name == name:
                    inputs = c.uses + c.declares + c.pulls
                    if input_types:
                        inputs = [i for i in inputs if i.input_type in input_types]
                    return p.render_inputs(inputs)
        raise self._not_found(name)

    def view_subgraph(
        self, name: str, perspective: type[Perspective[T]] | None = None, direction: str = "upstream"
    ) -> T:
        """Render subgraph. direction: 'upstream' (inputs), 'downstream' (dependents), or 'both'."""
        p = self._get(perspective)
        if name not in self._structure.graph:
            raise self._not_found(name)

        if direction == "upstream":
            subgraph = {}
            queue = [name]
            while queue:
                current = queue.pop()
                if current in subgraph or current not in self._structure.graph:
                    continue
                node = self._structure.graph[current]
                subgraph[current] = node
                queue.extend(node.inputs)
            return p.render_subgraph(subgraph)

        # Build reverse index for downstream
        dependents: dict[str, list[str]] = {}
        for n, node in self._structure.graph.items():
            for inp in node.inputs:
                dependents.setdefault(inp, []).append(n)

        # Collect downstream nodes
        down_names = set()
        queue = [name]
        while queue:
            current = queue.pop()
            if current in down_names or current not in self._structure.graph:
                continue
            down_names.add(current)
            for dep in dependents.get(current, []):
                queue.append(dep)

        # Build subgraph with reversed edges (dependents as inputs)
        down_subgraph = {}
        for n in down_names:
            orig = self._structure.graph[n]
            deps_in_subgraph = [d for d in dependents.get(n, []) if d in down_names]
            down_subgraph[n] = Node(name=n, kind=orig.kind, value=orig.value, inputs=deps_in_subgraph, atom=orig.atom)

        if direction == "downstream":
            return p.render_subgraph(down_subgraph)

        # Both: upstream with original edges + downstream with reversed edges
        up_subgraph = {}
        queue = [name]
        while queue:
            current = queue.pop()
            if current in up_subgraph or current not in self._structure.graph:
                continue
            node = self._structure.graph[current]
            up_subgraph[current] = node
            queue.extend(node.inputs)

        # Merge: upstream keeps original edges, downstream keeps reversed
        merged = dict(up_subgraph)
        for n, node in down_subgraph.items():
            if n in merged:
                combined_inputs = list(merged[n].inputs) + node.inputs
                orig = merged[n]
                merged[n] = Node(name=n, kind=orig.kind, value=orig.value, inputs=combined_inputs, atom=orig.atom)
            else:
                merged[n] = node
        return p.render_subgraph(merged)

    def view_kinds(self, perspective: type[Perspective[T]] | None = None) -> T:
        kinds: dict[NodeKind, list[str]] = {}
        for node in self._structure.graph.values():
            kinds.setdefault(node.kind, []).append(node.name)
        return self._get(perspective).render_kinds(kinds)

    def view_roots(self, perspective: type[Perspective[T]] | None = None) -> T:
        roots = self._structure.roots
        if roots is None:
            raise KeyError("No roots layer")
        return self._get(perspective).render_roots(roots)
