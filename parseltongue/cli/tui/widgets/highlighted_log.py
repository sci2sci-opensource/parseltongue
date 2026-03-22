"""HighlightedLog — RichLog with Pygments highlighting pipeline.

Scrollable, non-input-capturing log widget that pipes text through
the project's Pygments highlight pipeline before rendering.

Supports:
- Plain text (no highlight)
- Language-specific Pygments highlighting via ``_safe_highlight``
- Pre-rendered Rich markup passed through directly
- ``write()`` appends, ``set_content()`` replaces
"""

from __future__ import annotations

from textual.widgets import RichLog

from .pass_viewer import _safe_highlight, pv_escape


class HighlightedLog(RichLog):
    """RichLog that optionally highlights content via Pygments.

    Parameters
    ----------
    language
        Pygments lexer name (e.g. "scheme", "markdown", "text").
        ``None`` means pass text through as Rich markup (no Pygments).
    """

    DEFAULT_CSS = """
    HighlightedLog {
        height: 1fr;
    }
    """

    def __init__(
        self,
        *,
        language: str | None = None,
        wrap: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(wrap=wrap, markup=True, auto_scroll=False, **kwargs)
        self._language = language

    def set_content(self, text: str, *, language: str | None = ...) -> None:  # type: ignore[assignment]
        """Replace all content. Optionally override language for this call."""
        lang = self._language if language is ... else language
        self.clear()
        if not text:
            return
        markup = self._highlight_render(text, lang)
        self.write(markup)

    def append(self, text: str, *, language: str | None = ...) -> None:  # type: ignore[assignment]
        """Append highlighted text."""
        lang = self._language if language is ... else language
        markup = self._highlight_render(text, lang)
        self.write(markup)

    def set_info(self, text: str) -> None:
        """Replace content with dim info text (no highlight)."""
        self.clear()
        self.write(f"[dim]{pv_escape(text)}[/dim]")

    def set_error(self, text: str) -> None:
        """Replace content with red error text (no highlight)."""
        self.clear()
        self.write(f"[red]{pv_escape(text)}[/red]")

    @staticmethod
    def _highlight_render(text: str, language: str | None) -> str:
        """Render text to Rich markup, optionally via Pygments."""
        if language is None:
            # Pass through as-is (caller provides markup or plain text)
            return text
        return _safe_highlight(text, language)
