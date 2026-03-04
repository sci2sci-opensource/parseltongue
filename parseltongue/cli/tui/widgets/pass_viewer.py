"""PassViewer widget — syntax-highlighted pass output with clickable refs.

Used by both LivePassScreen (live execution) and PassesScreen (history).
Pygments tokenizes the source, output is Textual markup so @click works
inline alongside syntax colors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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


def pv_escape(text: str) -> str:
    """Escape text for safe use in PassViewer Textual markup.

    textual_escape handles '[' in most cases but misses standalone '['.
    Bare ']' inside styled spans (e.g. [italic]...[/italic]) prematurely
    closes the tag, so we must escape it too.
    """
    escaped = textual_escape(text)
    return escaped


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


_UNSAFE_RE = re.compile(r'(?<!\\)[\[\]]')


def _escape_brackets(escaped: str) -> str:
    """Escape any bare [ and ] that textual_escape missed."""
    return _UNSAFE_RE.sub(lambda m: f"\\{m.group()}", escaped)


def _wrap_safe(escaped: str, color: str) -> str:
    """Wrap escaped text in a color tag, escaping bare [ and ] first."""
    safe = _escape_brackets(escaped)
    return f"[{color}]{safe}[/{color}]"


def _token_color(token_type: object) -> str | None:
    """Find the best color for a Pygments token type, walking the hierarchy."""
    t = token_type
    while t is not Token:
        if t in _TOKEN_COLORS:
            return _TOKEN_COLORS[t]
        t = t.parent  # type: ignore[attr-defined]
    return None


# ---------------------------------------------------------------------------
# Special sequences — multi-token lexems that must be escaped as one unit
# ---------------------------------------------------------------------------


@dataclass
class TokenSlot:
    """Matches a single token position in a sequence."""

    token_type: object | None = None  # None = any type
    value: str | None = None  # None = any value

    def matches(self, tok_type: object, tok_val: str) -> bool:
        if self.token_type is not None and tok_type is not self.token_type:
            return False
        if self.value is not None and tok_val != self.value:
            return False
        return True


@dataclass
class LexemPattern:
    """A multi-token pattern that should be merged and escaped together."""

    slots: list[TokenSlot] = field(default_factory=list)
    color: str | None = None  # None = plain escaped text

    def try_match(self, tokens: list[tuple[object, str]], pos: int) -> int:
        """Return number of tokens consumed, or 0 if no match."""
        if pos + len(self.slots) > len(tokens):
            return 0
        for k, slot in enumerate(self.slots):
            if not slot.matches(*tokens[pos + k]):
                return 0
        return len(self.slots)

    def render(self, tokens: list[tuple[object, str]], pos: int, consumed: int) -> str:
        """Produce markup for matched tokens."""
        merged = "".join(tokens[pos + k][1] for k in range(consumed))
        escaped = pv_escape(merged)
        if self.color:
            return _wrap_safe(escaped, self.color)
        return _escape_brackets(escaped)


@dataclass
class RefPattern(LexemPattern):
    """Matches [[type:name]] references across tokens."""

    def try_match(self, tokens: list[tuple[object, str]], pos: int) -> int:
        if "[" not in tokens[pos][1]:
            return 0
        end = _try_ref(tokens, pos)
        return (end - pos) if end else 0

    def render(self, tokens: list[tuple[object, str]], pos: int, consumed: int) -> str:
        buf = "".join(tokens[pos + k][1] for k in range(consumed))
        m = _REF_RE.fullmatch(buf)
        ref_type, ref_name = m.group(1), m.group(2)  # type: ignore[union-attr]
        return (
            f"[@click=screen.ref_clicked('{ref_type}','{ref_name}')]"
            f"[bold cyan]{pv_escape(ref_name)}[/bold cyan]"
            f"[/]"
        )


@dataclass
class InlineRefPattern(LexemPattern):
    """Matches a single token containing [[type:name]] embedded in its value."""

    def try_match(self, tokens: list[tuple[object, str]], pos: int) -> int:
        return 1 if _REF_RE.search(tokens[pos][1]) else 0

    def render(self, tokens: list[tuple[object, str]], pos: int, consumed: int) -> str:
        tok_val = tokens[pos][1]
        parts: list[str] = []
        last = 0
        for m in _REF_RE.finditer(tok_val):
            before = tok_val[last : m.start()]
            if before:
                parts.append(_escape_brackets(pv_escape(before)))
            ref_type, ref_name = m.group(1), m.group(2)
            parts.append(
                f"[@click=screen.ref_clicked('{ref_type}','{ref_name}')]"
                f"[bold cyan]{pv_escape(ref_name)}[/bold cyan]"
                f"[/]"
            )
            last = m.end()
        after = tok_val[last:]
        if after:
            parts.append(_escape_brackets(pv_escape(after)))
        return "".join(parts)


@dataclass
class LanguageSpec:
    """Special sequence definitions for a language."""

    patterns: list[LexemPattern] = field(default_factory=list)


_LANGUAGE_SPECS: dict[str, LanguageSpec] = {
    "markdown": LanguageSpec(
        patterns=[
            RefPattern(),
            # [link text](url)
            LexemPattern(
                slots=[
                    TokenSlot(Token.Text, "["),
                    TokenSlot(Token.Name.Tag),
                    TokenSlot(Token.Text, "]"),
                    TokenSlot(Token.Text, "("),
                    TokenSlot(Token.Name.Attribute),
                    TokenSlot(Token.Text, ")"),
                ],
                color="cyan",
            ),
            # ![alt text](url)
            LexemPattern(
                slots=[
                    TokenSlot(Token.Text, "!["),
                    TokenSlot(Token.Name.Tag),
                    TokenSlot(Token.Text, "]"),
                    TokenSlot(Token.Text, "("),
                    TokenSlot(Token.Name.Attribute),
                    TokenSlot(Token.Text, ")"),
                ],
                color="dim cyan",
            ),
            # [label]: url  (footnote definition, starts with \n[ or [)
            LexemPattern(
                slots=[
                    TokenSlot(value=None),
                    TokenSlot(Token.Name.Label),
                    TokenSlot(Token.Text),
                    TokenSlot(Token.Name.Attribute),
                ],
                color="dim",
            ),
            InlineRefPattern(),
        ],
    ),
}


def _highlight(source: str, language: str) -> str:
    """Tokenize source with Pygments, return Textual markup with @click refs."""
    try:
        lexer = get_lexer_by_name(language)
    except Exception:
        lexer = get_lexer_by_name("text")

    tokens = [(t, v) for t, v in lex(source, lexer) if v]
    spec = _LANGUAGE_SPECS.get(language)
    patterns = spec.patterns if spec else []

    parts: list[str] = []
    i = 0
    while i < len(tokens):
        tok_type, tok_val = tokens[i]

        # 1. Try pattern matching (refs + language-specific sequences)
        matched = False
        for pattern in patterns:
            consumed = pattern.try_match(tokens, i)
            if consumed:
                parts.append(pattern.render(tokens, i, consumed))
                i += consumed
                matched = True
                break
        if matched:
            continue

        # 2. Single token — colorize
        escaped = pv_escape(tok_val)
        color = _token_color(tok_type)
        if color:
            parts.append(_wrap_safe(escaped, color))
        else:
            parts.append(_escape_brackets(escaped))
        i += 1

    return "".join(parts)


def _try_ref(tokens: list[tuple[object, str]], start: int) -> int | None:
    """Try to match [[type:name]] across tokens starting at start.

    Returns the exclusive end index, or None if no match.
    """
    buf = ""
    for k in range(start, min(start + 10, len(tokens))):
        buf += tokens[k][1]
        if buf.endswith("]]"):
            if _REF_RE.fullmatch(buf):
                return k + 1
            return None
        if len(buf) > 2 and not buf.startswith("[["):
            return None
    return None


def _safe_highlight(source: str, language: str) -> str:
    """Highlight with graceful fallback — never crash on bad markup."""
    try:
        markup = _highlight(source, language)
        # Validate by letting Textual parse it; raises on bad tags
        from textual.markup import to_content

        to_content(markup)
        return markup
    except Exception:
        import logging
        import traceback

        logging.getLogger("parseltongue.cli").warning(
            "Syntax highlight failed for %s content (source %d chars):\n%s",
            language,
            len(source),
            traceback.format_exc(),
        )
        return f"[dim yellow](System comment: highlight unavailable)[/dim yellow]\n\n{pv_escape(source)}"


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
        self._markup = _safe_highlight(self._source, self._language)
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
        self._markup = _safe_highlight(source, self._language)
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
