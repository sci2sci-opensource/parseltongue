"""Hints bar — consistent keyboard shortcut hints docked at the bottom."""

from __future__ import annotations

from textual.widgets import Static


class HintsBar(Static):
    """Single-line bar showing keyboard shortcuts in [b]Key[/b] Action format."""

    DEFAULT_CSS = """
    HintsBar {
        dock: bottom;
        height: 2;
        color: $text-muted;
        padding: 1 1 0 1;
    }
    """

    def __init__(self, hints: list[tuple[str, str]], **kwargs) -> None:
        markup = "  ".join(f"[b]{key}[/b] {desc}" for key, desc in hints)
        super().__init__(markup, **kwargs)
