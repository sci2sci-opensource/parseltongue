"""Optics — abstract base for optical instruments that view provenance structures."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from ..perspective import Perspective
from ..probe_core_to_consequence import InputType

T = TypeVar("T")


class Optics(ABC):
    """Abstract base for provenance viewers.

    Subclasses: Lens (single structure), Hologram (two structures side-by-side).
    Search is handled by dedicated search systems (LensSearchSystem,
    HologramSearchSystem) registered as scopes in the main search engine.
    """

    @abstractmethod
    def focus(self, name: str) -> "Optics":
        """Narrow view to the substructure around *name*."""

    @abstractmethod
    def view(self, perspective: type[Perspective[T]] | None = None) -> T:
        """Render the full structure."""

    @abstractmethod
    def view_node(self, name: str, perspective: type[Perspective[T]] | None = None) -> T:
        """Render a single node."""

    @abstractmethod
    def view_consumer(self, name: str, perspective: type[Perspective[T]] | None = None) -> T:
        """Render a consumer (node with inputs)."""

    @abstractmethod
    def view_inputs(self, name: str, perspective: type[Perspective[T]] | None = None, *input_types: InputType) -> T:
        """Render inputs of a consumer."""

    @abstractmethod
    def view_subgraph(
        self, name: str, perspective: type[Perspective[T]] | None = None, direction: str = "upstream"
    ) -> T:
        """Render subgraph around *name*."""

    @abstractmethod
    def view_layer(self, depth: int, perspective: type[Perspective[T]] | None = None) -> T:
        """Render one layer."""

    @abstractmethod
    def view_kinds(self, perspective: type[Perspective[T]] | None = None) -> T:
        """Render node kinds with counts."""

    @abstractmethod
    def view_roots(self, perspective: type[Perspective[T]] | None = None) -> T:
        """Render root nodes."""
