"""PassViewer widget — syntax-highlighted pass output with clickable refs.

Used by both LivePassScreen (live execution) and PassesScreen (history).
Pygments tokenizes the source, output is Textual markup so @click works
inline alongside syntax colors.
"""

from __future__ import annotations

import re

from pygments import lex
from pygments.lexers import get_lexer_by_name
from pygments.token import Token
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.markup import escape as textual_escape
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

_REF_RE = re.compile(r"\[\[(\w+):([^\]]+)\]\]")

# Map Pygments token types to Textual color names
_TOKEN_COLORS: dict[object, str] = {
    Token.Keyword: "magenta",
    Token.Keyword.Declaration: "magenta",
    Token.Name.Builtin: "cyan",
    Token.Name.Function: "green",
    Token.Name.Variable: "white",
    Token.Name: "white",
    Token.String: "yellow",
    Token.Literal.String: "yellow",
    Token.Literal.String.Symbol: "yellow",
    Token.Literal.Number: "cyan",
    Token.Literal.Number.Integer: "cyan",
    Token.Literal.Number.Float: "cyan",
    Token.Comment: "dim green",
    Token.Comment.Single: "dim green",
    Token.Comment.Multiline: "dim green",
    Token.Operator: "red",
    Token.Punctuation: "white",
    Token.Generic.Heading: "bold green",
    Token.Generic.Subheading: "bold green",
    Token.Generic.Emph: "italic",
    Token.Generic.Strong: "bold",
    Token.Generic.EmphStrong: "bold italic",
}


def _token_color(token_type: object) -> str | None:
    """Find the best color for a Pygments token type, walking the hierarchy."""
    t = token_type
    while t is not Token:
        if t in _TOKEN_COLORS:
            return _TOKEN_COLORS[t]
        t = t.parent  # type: ignore[attr-defined]
    return None


def _highlight(source: str, language: str) -> str:
    """Tokenize source with Pygments, return Textual markup with @click refs."""
    try:
        lexer = get_lexer_by_name(language)
    except Exception:
        lexer = get_lexer_by_name("text")

    parts: list[str] = []
    for token_type, value in lex(source, lexer):
        if not value:
            continue

        # Check for [[type:name]] refs in this token's text
        ref_match = _REF_RE.search(value)
        if ref_match:
            # Split around refs, linkify them
            last = 0
            for m in _REF_RE.finditer(value):
                before = value[last : m.start()]
                if before:
                    parts.append(textual_escape(before))
                ref_type, ref_name = m.group(1), m.group(2)
                parts.append(
                    f"[@click=screen.ref_clicked('{ref_type}','{ref_name}')]"
                    f"[bold cyan]{textual_escape(ref_name)}[/bold cyan]"
                    f"[/]"
                )
                last = m.end()
            after = value[last:]
            if after:
                parts.append(textual_escape(after))
            continue

        escaped = textual_escape(value)
        color = _token_color(token_type)
        if color:
            parts.append(f"[{color}]{escaped}[/{color}]")
        else:
            parts.append(escaped)

    return "".join(parts)


class PassViewer(Widget):
    """Syntax-highlighted source viewer with inline clickable refs."""

    class RefClicked(Message):
        """Posted when a [[type:name]] reference link is clicked."""

        def __init__(self, ref_type: str, ref_name: str) -> None:
            super().__init__()
            self.ref_type = ref_type
            self.ref_name = ref_name

    DEFAULT_CSS = """
    PassViewer {
        height: 1fr;
    }
    PassViewer VerticalScroll {
        height: 1fr;
    }
    PassViewer Static {
        link-color: cyan;
        link-style: bold underline;
    }
    """

    def __init__(
        self,
        source: str = "",
        language: str = "scheme",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._source = source
        self._language = language
        self._markup = ""

    def compose(self) -> ComposeResult:
        self._markup = _highlight(self._source, self._language)
        with VerticalScroll():
            yield Static(self._markup, id="pv-source")

    @property
    def plain_text(self) -> str:
        return self._source

    def set_source(self, source: str, language: str | None = None) -> None:
        """Replace content with new highlighted source."""
        if language is not None:
            self._language = language
        self._source = source
        self._markup = _highlight(source, self._language)
        try:
            self.query_one("#pv-source", Static).update(self._markup)
        except Exception:
            pass

    def append_error(self, error: str) -> None:
        """Append error text to the source display."""
        self._markup += f"\n[red]{textual_escape(error)}[/red]"
        try:
            self.query_one("#pv-source", Static).update(self._markup)
        except Exception:
            pass

    def append_info(self, text: str) -> None:
        """Append info text to the source display."""
        self._markup += f"\n[dim]{textual_escape(text)}[/dim]"
        try:
            self.query_one("#pv-source", Static).update(self._markup)
        except Exception:
            pass

    def action_ref_clicked(self, ref_type: str, ref_name: str) -> None:
        """Handle click on a [[type:name]] link."""
        self.post_message(self.RefClicked(ref_type, ref_name))
