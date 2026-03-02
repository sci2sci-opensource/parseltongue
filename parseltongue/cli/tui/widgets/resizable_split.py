"""Mixin for keyboard-resizable split panes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.css.scalar import Scalar, Unit

if TYPE_CHECKING:
    from textual.widget import Widget

_FR = Unit.FRACTION
_STEP = 0.2
_MIN = 0.5


def _fr(value: float) -> Scalar:
    return Scalar(value, _FR, _FR)


class ResizableSplitMixin:
    """Mixin that adds Ctrl+Left / Ctrl+Right to resize a two-column grid.

    Subclasses must set ``_split_grid_id`` to the CSS id of the grid
    container (without ``#``), or ``None`` if the screen itself is the grid.
    """

    _split_grid_id: str | None = None
    _split_left: float = 2.0
    _split_right: float = 1.0

    def _get_grid(self) -> Widget:
        self_widget: Widget = self
        if self._split_grid_id is not None:
            return self_widget.query_one(f"#{self._split_grid_id}")
        return self_widget

    def _apply_split(self) -> None:
        grid = self._get_grid()
        grid.styles.grid_columns = (_fr(self._split_left), _fr(self._split_right))

    def action_grow_left(self) -> None:
        self._split_left = min(self._split_left + _STEP, 6.0)
        self._split_right = max(self._split_right - _STEP, _MIN)
        self._apply_split()

    def action_grow_right(self) -> None:
        self._split_left = max(self._split_left - _STEP, _MIN)
        self._split_right = min(self._split_right + _STEP, 6.0)
        self._apply_split()
