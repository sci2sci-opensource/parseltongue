"""Shared color definitions for Parseltongue TUI syntax highlighting.

Single source of truth used by both:
- PassViewer (Pygments-based, read-only Rich markup)
- TextArea editor (Pygments-based, editable)

Every color and style modifier is defined once in PALETTE.
TOKEN_STYLES maps Pygments tokens → palette keys.
Both PassViewer and the TextArea theme consume the same resolved values.
"""

from __future__ import annotations

from dataclasses import dataclass

from pygments.token import Token
from rich.style import Style
from textual._text_area_theme import TextAreaTheme

# ---------------------------------------------------------------------------
# Palette — every syntax color defined exactly once
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SyntaxStyle:
    """A single syntax color definition.

    Stores Rich color names (e.g. "cyan", "magenta") as canonical values.
    Named colors produce ANSI escape codes that the terminal renders
    consistently across both PassViewer (Rich markup) and TextArea (Style).
    """

    color: str  # Rich color name, e.g. "cyan", "magenta"
    dim: bool = False
    bold: bool = False
    italic: bool = False

    def to_rich_markup_tag(self) -> str:
        """Return a Rich markup tag string for PassViewer."""
        parts = []
        if self.bold:
            parts.append("bold")
        if self.dim:
            parts.append("dim")
        if self.italic:
            parts.append("italic")
        parts.append(self.color)
        return " ".join(parts)

    def to_rich_style(self) -> Style:
        """Return a Rich Style for TextArea theme."""
        return Style(
            color=self.color,
            dim=self.dim,
            bold=self.bold,
            italic=self.italic,
        )


# The palette — change colors here, both viewers update.
# Uses Rich named colors to match terminal ANSI palette exactly.
PALETTE = {
    "function": SyntaxStyle("green"),
    "builtin": SyntaxStyle("cyan"),
    "variable": SyntaxStyle("white"),
    "string": SyntaxStyle("yellow"),
    "number": SyntaxStyle("cyan"),
    "comment": SyntaxStyle("green", dim=True),
    "keyword": SyntaxStyle("magenta", dim=True),
    "operator": SyntaxStyle("red"),
    "punctuation": SyntaxStyle("white"),
    "heading": SyntaxStyle("green", bold=True),
    "emph": SyntaxStyle("white", italic=True),
    "strong": SyntaxStyle("white", bold=True),
    "emph_strong": SyntaxStyle("white", bold=True, italic=True),
    "error": SyntaxStyle("red", bold=True),
    "unreachable": SyntaxStyle("white", dim=True),
}


# ---------------------------------------------------------------------------
# Pygments token → palette key mapping
# ---------------------------------------------------------------------------

_TOKEN_PALETTE: dict[object, str] = {
    Token.Keyword: "keyword",
    Token.Keyword.Declaration: "keyword",
    Token.Keyword.Namespace: "keyword",
    Token.Name.Builtin: "builtin",
    Token.Name.Function: "function",
    Token.Name.Variable: "variable",
    Token.Name.Decorator: "keyword",
    Token.Name.Class: "builtin",
    Token.Name.Namespace: "builtin",
    Token.Name: "variable",
    Token.String: "string",
    Token.Literal.String: "string",
    Token.Literal.String.Symbol: "string",
    Token.Literal.String.Doc: "string",
    Token.Literal.Number: "number",
    Token.Literal.Number.Integer: "number",
    Token.Literal.Number.Float: "number",
    Token.Comment: "comment",
    Token.Comment.Single: "comment",
    Token.Comment.Multiline: "comment",
    Token.Comment.Hashbang: "comment",
    Token.Operator: "operator",
    Token.Operator.Word: "keyword",
    Token.Punctuation: "punctuation",
    Token.Generic.Heading: "heading",
    Token.Generic.Subheading: "heading",
    Token.Generic.Emph: "emph",
    Token.Generic.Strong: "strong",
    Token.Generic.EmphStrong: "emph_strong",
    Token.Keyword.Type: "builtin",
    Token.Keyword.Constant: "builtin",
}


# Pltg-specific keywords that Pygments doesn't recognise as keywords
# Colon-prefixed pltg keywords that Pygments doesn't recognise
PLTG_KEYWORDS: set[str] = {
    ":quotes",
    ":explanation",
    ":origin",
    ":evidence",
    ":using",
    ":replace",
    ":with",
    ":bind",
}


def resolve_highlight(token_type: object, token_value: str) -> str | None:
    """Return a palette key for a Pygments token, considering pltg keywords.

    Centralised logic used by both PassViewer and PygmentsTextArea.
    """
    # Pltg keyword override — Pygments treats these as variables/functions
    stripped = token_value.strip()
    if stripped in PLTG_KEYWORDS:
        return "keyword"

    t = token_type
    while t is not Token:
        if t in _TOKEN_PALETTE:
            return _TOKEN_PALETTE[t]
        t = t.parent  # type: ignore[attr-defined]
    return None


def token_color(token_type: object, token_value: str = "") -> str | None:
    """Return a Rich markup tag string for a Pygments token.

    Used by PassViewer to wrap text in color tags.
    """
    key = resolve_highlight(token_type, token_value)
    return PALETTE[key].to_rich_markup_tag() if key else None


def token_highlight_name(token_type: object, token_value: str = "") -> str | None:
    """Return a TextArea theme highlight name for a Pygments token.

    Used by PygmentsTextArea to populate the highlight map.
    """
    return resolve_highlight(token_type, token_value)


# ---------------------------------------------------------------------------
# TextArea theme — built from the same PALETTE
# ---------------------------------------------------------------------------

PLTG_THEME = TextAreaTheme(
    name="pltg",
    syntax_styles={key: style.to_rich_style() for key, style in PALETTE.items()},
)
