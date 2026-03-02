"""DSL viewer widget — syntax-highlighted DSL code display."""

from __future__ import annotations

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static


class DslViewer(Widget):
    """Read-only viewer for DSL source code with Pygments syntax highlighting."""

    def __init__(self, source: str, language: str = "scheme", **kwargs) -> None:
        super().__init__(**kwargs)
        self._source = source
        self._language = language

    def compose(self) -> ComposeResult:
        syntax = Syntax(
            self._source,
            self._language,
            line_numbers=True,
            word_wrap=True,
        )
        with VerticalScroll():
            yield Static(syntax)
