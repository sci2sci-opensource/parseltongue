"""Status bar widget — shows keybinding hints at the bottom."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class StatusBar(Widget):
    """Bottom bar with keyboard shortcut hints."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $primary;
        layout: horizontal;
    }
    StatusBar .hint {
        width: auto;
        padding: 0 1;
    }
    StatusBar .hint .key {
        text-style: bold;
    }
    """

    HINTS = [
        ("F1", "Answer"),
        ("F2", "Passes"),
        ("F3", "System"),
        ("F4", "Consistency"),
        ("Esc", "Back"),
    ]

    def compose(self) -> ComposeResult:
        for key, desc in self.HINTS:
            yield Static(f"[b]{key}[/b] {desc}", classes="hint")
