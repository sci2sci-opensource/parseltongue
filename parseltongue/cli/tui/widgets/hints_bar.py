"""Hints bar — consistent keyboard shortcut hints docked at the bottom."""

from __future__ import annotations

from collections.abc import Sequence

from textual.containers import Horizontal
from textual.widgets import Static


class HintItem(Static):
    """A single hint that triggers an action on Enter or click. Focusable only when actionable."""

    DEFAULT_CSS = """
    HintItem {
        width: auto;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    HintItem:focus {
        color: $text;
        text-style: reverse;
    }
    """

    def __init__(self, key: str, desc: str, action: str | None = None, **kwargs) -> None:
        self._action = action
        self.can_focus = action is not None
        markup = f"[b]{key}[/b] {desc}"
        if action:
            markup = f"[@click={action}]{markup}[/]"
        super().__init__(markup, **kwargs)

    def key_enter(self) -> None:
        if self._action:
            self.set_timer(0.1, lambda: self.screen.run_action(self._action))


class HintsBar(Horizontal):
    """Bar of focusable hint items docked at the bottom.

    Each hint is a tuple of (key_label, description) or
    (key_label, description, action) where action makes it clickable and tab-selectable.
    """

    DEFAULT_CSS = """
    HintsBar {
        dock: bottom;
        height: 3;
        color: $text-muted;
        padding: 1 2 1 2;
    }
    """

    def __init__(self, hints: Sequence[tuple[str, ...]], **kwargs) -> None:
        self._hints = hints
        super().__init__(**kwargs)

    def compose(self):
        for hint in self._hints:
            key, desc = hint[0], hint[1]
            action = hint[2] if len(hint) > 2 else None
            yield HintItem(key, desc, action)
