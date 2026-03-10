"""TUI widgets."""

from textual import events
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Tree


class FocusedScroll(VerticalScroll):
    """VerticalScroll that only scrolls when focused."""

    can_focus = True

    DEFAULT_CSS = """
    FocusedScroll {
        overflow-x: hidden;
        overflow-y: hidden;
    }
    FocusedScroll:focus {
        overflow-y: auto;
    }
    """

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if self.has_focus:
            self.scroll_down(animate=False)
        event.stop()

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if self.has_focus:
            self.scroll_up(animate=False)
        event.stop()

    def on_click(self, event: events.Click) -> None:
        self.focus(scroll_visible=False)


class _InnerTree(Tree):
    """Tree with all scrolling killed. Renders at full content height."""

    DEFAULT_CSS = """
    _InnerTree {
        overflow-x: hidden;
        overflow-y: hidden;
        height: auto;
        width: auto;
    }
    """

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()


class FocusedTree(FocusedScroll):
    """Focus-gated scrollable tree via composition.

    Contains a dumb _InnerTree that just renders at full size.
    FocusedScroll handles all scrolling on focus/click.
    Exposes Tree API (root, clear, move_cursor, etc.) by proxying to inner tree.
    """

    DEFAULT_CSS = """
    FocusedTree {
        overflow-x: hidden;
        overflow-y: hidden;
    }
    FocusedTree:focus {
        overflow-x: auto;
        overflow-y: auto;
    }
    FocusedTree.always-scroll {
        overflow-x: auto;
        overflow-y: auto;
    }
    """

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if self.has_focus or not self._require_focus:
            self.scroll_down(animate=False)
        event.stop()

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if self.has_focus or not self._require_focus:
            self.scroll_up(animate=False)
        event.stop()

    def _on_mouse_scroll_right(self, event: events.MouseScrollRight) -> None:
        if self.has_focus or not self._require_focus:
            self.scroll_right(animate=False)
        event.stop()

    def _on_mouse_scroll_left(self, event: events.MouseScrollLeft) -> None:
        if self.has_focus or not self._require_focus:
            self.scroll_left(animate=False)
        event.stop()

    def __init__(self, label: str = "Tree", *, require_focus: bool = True, **kwargs) -> None:
        super().__init__(**kwargs)
        self._require_focus = require_focus
        self._inner = _InnerTree(label)
        if not require_focus:
            self.add_class("always-scroll")

    def compose(self) -> ComposeResult:
        yield self._inner

    @property
    def root(self):
        return self._inner.root

    def clear(self):
        return self._inner.clear()

    def move_cursor(self, node):
        return self._inner.move_cursor(node)

    def scroll_to_node(self, node) -> None:
        """Move cursor to node and scroll it into view."""
        self._inner.move_cursor(node)
        # _InnerTree can't scroll (overflow hidden), so scroll the outer container
        y = self._inner.cursor_line
        self.scroll_to(0, y, animate=False)
