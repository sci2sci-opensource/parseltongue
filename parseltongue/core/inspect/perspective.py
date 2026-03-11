"""Perspective — a way to view parts of a CoreToConsequenceStructure."""

from typing import Generic, TypeVar

from .probe_core_to_consequence import (
    Consumer,
    ConsumerInput,
    CoreToConsequenceStructure,
    Layer,
    Node,
    NodeKind,
)

T = TypeVar("T")


class Perspective(Generic[T]):
    """Base class for perspectives.

    T is the view type this perspective produces (e.g. Ascii, Html).
    Subclass and implement render methods.
    """

    def render_structure(self, structure: CoreToConsequenceStructure) -> T:
        raise NotImplementedError

    def render_layer(self, layer: Layer) -> T:
        raise NotImplementedError

    def render_consumer(self, consumer: Consumer) -> T:
        raise NotImplementedError

    def render_node(self, node: Node) -> T:
        raise NotImplementedError

    def render_inputs(self, inputs: list[ConsumerInput]) -> T:
        raise NotImplementedError

    def render_subgraph(self, nodes: dict[str, Node]) -> T:
        raise NotImplementedError

    def render_kinds(self, kinds: dict[NodeKind, list[str]]) -> T:
        raise NotImplementedError

    def render_roots(self, layer: Layer) -> T:
        raise NotImplementedError
