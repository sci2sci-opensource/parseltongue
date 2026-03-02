"""DSL viewer widget — syntax-highlighted DSL code display."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import TextArea


class DslViewer(Widget):
    """Read-only viewer for DSL source code with syntax highlighting."""

    def __init__(self, source: str, language: str = "scheme", **kwargs) -> None:
        super().__init__(**kwargs)
        self._source = source
        self._language = language

    def compose(self) -> ComposeResult:
        text_area = TextArea(
            self._source,
            language=self._language,
            read_only=True,
            show_line_numbers=True,
        )
        yield text_area
