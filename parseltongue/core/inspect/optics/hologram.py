"""Hologram — multi-structure optic for viewing N lenses simultaneously.

Created via ``bench.dissect(diff_name)`` (2 lenses) or
``bench.compose(lens1, lens2, ...)`` (N lenses).
A Bias controls how outputs from all lenses are combined.

Usage::

    holo = bench.dissect("thm-readme-special-forms")
    print(holo.view())                      # default: Bias.NEUTRAL
    print(holo.bias(Bias.DIVERGENCE).view())

    holo3 = bench.compose(lens_a, lens_b, lens_c)
    print(holo3.bias(Bias.LEFT).view())
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from ..perspective import Perspective
from ..probe_core_to_consequence import InputType
from .base import Optics
from .lens import Lens

T = TypeVar("T")


# ── Bias ──


class Bias:
    """Pure combination functions for hologram outputs.

    A Bias is callable: ``bias(outputs, labels) -> combined``.
    Use the class constants: ``Bias.NEUTRAL``, ``Bias.LEFT``, etc.
    """

    NEUTRAL: "Bias"
    LEFT: "Bias"
    RIGHT: "Bias"
    DIVERGENCE: "Bias"

    def __init__(self, fn: Callable[[list[Any], list[str]], Any]):
        self._fn = fn

    def __call__(self, outputs: list[Any], labels: list[str]) -> Any:
        return self._fn(outputs, labels)

    @staticmethod
    def _neutral(outputs: list[Any], labels: list[str]) -> Any:
        sep = "=" * 60
        parts = []
        for label, out in zip(labels, outputs):
            val = str(out) if out is not None else "(absent)"
            parts.append(f"{label:^60}\n{sep}\n{val}")
        return "\n\n".join(parts)

    @staticmethod
    def _left(outputs: list[Any], labels: list[str]) -> Any:
        parts = []
        for i, (label, out) in enumerate(zip(labels, outputs)):
            if i == 0:
                parts.append(str(out) if out is not None else "(absent)")
            elif out is not None:
                context = "\n".join(f"  | {line}" for line in str(out).splitlines())
                parts.append(f"  {label}:\n{context}")
        return "\n".join(parts)

    @staticmethod
    def _right(outputs: list[Any], labels: list[str]) -> Any:
        parts: list[str] = []
        last = len(outputs) - 1
        for i, (label, out) in enumerate(zip(labels, outputs)):
            if i == last:
                parts.insert(0, str(out) if out is not None else "(absent)")
            elif out is not None:
                context = "\n".join(f"  | {line}" for line in str(out).splitlines())
                parts.append(f"  {label}:\n{context}")
        return "\n".join(parts)

    @staticmethod
    def _divergence(outputs: list[Any], labels: list[str]) -> Any:
        strs = [str(o) if o is not None else "(absent)" for o in outputs]
        if len(set(strs)) <= 1:
            return None
        sep = "-" * 60
        parts = [f"[{label}]\n{s}" for label, s in zip(labels, strs)]
        return f"\n{sep}\n".join(parts)


Bias.NEUTRAL = Bias(Bias._neutral)
Bias.LEFT = Bias(Bias._left)
Bias.RIGHT = Bias(Bias._right)
Bias.DIVERGENCE = Bias(Bias._divergence)


# ── Hologram ──


class Hologram(Optics):
    """Multi-structure optic — N Lenses combined via a Bias.

    Each Lens keeps its own perspectives. The bias controls
    how their outputs are arranged together.

    ``holo.bias(Bias.LEFT)`` returns a new Hologram with a different bias.
    The lenses are shared, not copied.
    """

    def __init__(
        self,
        lenses: list[Lens],
        name: str = "",
        labels: list[str] | None = None,
        _bias: Bias | None = None,
    ):
        if len(lenses) < 2:
            raise ValueError("Hologram requires at least 2 lenses")
        self._lenses = lenses
        self._name = name
        self._labels = labels or [f"L{i}" for i in range(len(lenses))]
        self._bias = _bias or Bias.NEUTRAL
        self.__names: set[str] | None = None

    @property
    def left(self) -> Lens:
        """First lens."""
        return self._lenses[0]

    @property
    def right(self) -> Lens:
        """Last lens."""
        return self._lenses[-1]

    def __getitem__(self, i: int) -> Lens:
        return self._lenses[i]

    def __len__(self) -> int:
        return len(self._lenses)

    @property
    def _names(self) -> set[str]:
        if self.__names is None:
            self.__names = set()
            for lens in self._lenses:
                self.__names |= lens._names
        return self.__names

    def bias(self, b: Bias) -> "Hologram":
        """Return a new Hologram with a different bias. Same lenses."""
        return Hologram(self._lenses, self._name, self._labels, b)

    def _not_found(self, name: str) -> KeyError:
        suggestions = self.fuzzy(name)
        msg = f"No {name!r} on any lens"
        if suggestions:
            msg += f". Did you mean: {', '.join(suggestions)}"
        return KeyError(msg)

    def _combine(self, fn) -> Any:
        """Call fn(lens) for each lens, combine via bias."""
        outputs = []
        all_err = True
        last_err: KeyError | None = None
        for lens in self._lenses:
            try:
                outputs.append(fn(lens))
                all_err = False
            except KeyError as e:
                outputs.append(None)
                last_err = e
        if all_err and last_err is not None:
            raise last_err
        return self._bias(outputs, self._labels)

    # ── Optics interface ──

    def focus(self, name: str) -> "Hologram":
        focused = []
        for lens in self._lenses:
            try:
                focused.append(lens.focus(name))
            except KeyError:
                focused.append(lens)
        return Hologram(focused, self._name, self._labels, self._bias)

    def view(self, perspective: type[Perspective[T]] | None = None) -> Any:
        return self._combine(lambda lens: lens.view(perspective))

    def view_node(self, name: str, perspective: type[Perspective[T]] | None = None) -> Any:
        return self._combine(lambda lens: lens.view_node(name, perspective))

    def view_consumer(self, name: str, perspective: type[Perspective[T]] | None = None) -> Any:
        return self._combine(lambda lens: lens.view_consumer(name, perspective))

    def view_inputs(self, name: str, perspective: type[Perspective[T]] | None = None, *input_types: InputType) -> Any:
        return self._combine(lambda lens: lens.view_inputs(name, perspective, *input_types))

    def view_subgraph(
        self, name: str, perspective: type[Perspective[T]] | None = None, direction: str = "upstream"
    ) -> Any:
        return self._combine(lambda lens: lens.view_subgraph(name, perspective, direction))

    def view_layer(self, depth: int, perspective: type[Perspective[T]] | None = None) -> Any:
        return self._combine(lambda lens: lens.view_layer(depth, perspective))

    def view_kinds(self, perspective: type[Perspective[T]] | None = None) -> Any:
        return self._combine(lambda lens: lens.view_kinds(perspective))

    def view_roots(self, perspective: type[Perspective[T]] | None = None) -> Any:
        return self._combine(lambda lens: lens.view_roots(perspective))
