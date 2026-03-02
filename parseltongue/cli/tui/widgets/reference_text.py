"""Reference text widget — markdown with clickable footnote references."""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.rules_inline import StateInline
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.content import Content, Span
from textual.message import Message
from textual.style import Style
from textual.widgets import Markdown, Static
from textual.widgets._markdown import MarkdownBlock

TAG_RE = re.compile(r"\[\[(\w+):([^\]]+)\]\]")

# ---------------------------------------------------------------------------
# ==mark== plugin for markdown-it  (produces mark_open / mark_close tokens)
# ---------------------------------------------------------------------------


def _mark_rule(state: StateInline, silent: bool) -> bool:
    start = state.pos
    if state.src[start : start + 2] != "==":
        return False
    # Opening == : must have a closing == ahead
    if not getattr(state, "_mark_open", False):
        if state.src.find("==", start + 2) < 0:
            return False
        if not silent:
            state.push("mark_open", "mark", 1).markup = "=="
            state._mark_open = True
        state.pos = start + 2
        return True
    # Closing ==
    if not silent:
        state.push("mark_close", "mark", -1).markup = "=="
        state._mark_open = False
    state.pos = start + 2
    return True


def _mark_plugin(md: MarkdownIt) -> None:
    md.inline.ruler.push("mark", _mark_rule)


def _make_parser() -> MarkdownIt:
    return MarkdownIt("gfm-like").use(_mark_plugin)


# ---------------------------------------------------------------------------
# Extend MarkdownBlock._token_to_content to handle mark_open → ".mark"
# Textual has no inline-token extension point, so we replace the method.
# ---------------------------------------------------------------------------

MarkdownBlock.COMPONENT_CLASSES = MarkdownBlock.COMPONENT_CLASSES | {"mark"}


def _token_to_content_with_mark(self, token):  # noqa: ANN001
    """_token_to_content extended with mark_open support."""
    if token.children is None:
        return Content("")

    tokens: list[str] = []
    spans: list[Span] = []
    style_stack: list[tuple[Style | str, int]] = []
    position: int = 0

    def add_content(text: str) -> None:
        nonlocal position
        tokens.append(text)
        position += len(text)

    def add_style(style: Style | str) -> None:
        style_stack.append((style, position))

    def close_tag() -> None:
        style, start = style_stack.pop()
        spans.append(Span(start, position, style))

    for child in token.children:
        child_type = child.type
        if child_type == "text":
            add_content(re.sub(r"\s+", " ", child.content))
        if child_type == "hardbreak":
            add_content("\n")
        if child_type == "softbreak":
            add_content(" ")
        elif child_type == "code_inline":
            add_style(".code_inline")
            add_content(child.content)
            close_tag()
        elif child_type == "em_open":
            add_style(".em")
        elif child_type == "strong_open":
            add_style(".strong")
        elif child_type == "s_open":
            add_style(".s")
        elif child_type == "mark_open":
            add_style(".mark")
        elif child_type == "link_open":
            href = child.attrs.get("href", "")
            action = f"link({href!r})"
            add_style(Style.from_meta({"@click": action}))
        elif child_type == "image":
            href = child.attrs.get("src", "")
            alt = child.attrs.get("alt", "")
            action = f"link({href!r})"
            add_style(Style.from_meta({"@click": action}))
            add_content("\U0001f5bc  ")
            if alt:
                add_content(f"({alt})")
            if child.children is not None:
                for grandchild in child.children:
                    add_content(grandchild.content)
            close_tag()
        elif child_type.endswith("_close"):
            close_tag()

    return Content("".join(tokens), spans=spans)


MarkdownBlock._token_to_content = _token_to_content_with_mark


# ---------------------------------------------------------------------------
# Messages and widgets
# ---------------------------------------------------------------------------


class ReferenceClicked(Message):
    """Posted when a [[type:name]] reference is clicked."""

    def __init__(self, ref_type: str, ref_name: str) -> None:
        super().__init__()
        self.ref_type = ref_type
        self.ref_name = ref_name


class FootnoteLabel(Static):
    """Clickable footnote label for a reference."""

    DEFAULT_CSS = """
    FootnoteLabel {
        height: auto;
    }
    """

    def __init__(self, ref_type: str, ref_name: str, num: int, **kwargs) -> None:
        self.ref_type = ref_type
        self.ref_name = ref_name
        self.num = num
        super().__init__(**kwargs)

    def on_mount(self) -> None:
        self.update(self._format(active=False))

    def _format(self, *, active: bool) -> str:
        if active:
            return f"  [cyan bold]\\[{self.num}] {self.ref_name}[/cyan bold]"
        return f"  \\[{self.num}] {self.ref_name}"

    def set_active(self, *, active: bool) -> None:
        self.update(self._format(active=active))

    def on_click(self) -> None:
        self.post_message(ReferenceClicked(self.ref_type, self.ref_name))


class ReferenceText(VerticalScroll):
    """Scrollable markdown display with clickable footnote references."""

    def __init__(self, markdown_text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._raw = markdown_text
        self._footnotes: dict[tuple[str, str], int] = {}
        self._active_ref: tuple[str, str] | None = None
        self._link_clicked = False

    def _collect_footnotes(self) -> dict[tuple[str, str], int]:
        footnotes: dict[tuple[str, str], int] = {}
        for m in TAG_RE.finditer(self._raw):
            key = (m.group(1), m.group(2))
            if key not in footnotes:
                footnotes[key] = len(footnotes) + 1
        return footnotes

    def _build_body(self) -> str:
        active = self._active_ref

        def _replace_ref(m: re.Match) -> str:
            ref_type, ref_name = m.group(1), m.group(2)
            key = (ref_type, ref_name)
            num = self._footnotes.get(key, 0)
            if active and key == active:
                # No link — already selected; mark renders cyan
                return f"==\\[{num}\\]=="
            return f"[\\[{num}\\]]({ref_type}:{ref_name})"

        return TAG_RE.sub(_replace_ref, self._raw)

    def compose(self) -> ComposeResult:
        self._footnotes = self._collect_footnotes()

        yield Markdown(
            self._build_body(),
            open_links=False,
            parser_factory=_make_parser,
        )

        if self._footnotes:
            yield Static("───", id="footnote-divider")
            for (ref_type, ref_name), num in self._footnotes.items():
                yield FootnoteLabel(ref_type, ref_name, num)

    def highlight_ref(self, ref_type: str, ref_name: str) -> None:
        """Highlight the active reference in body and footnotes."""
        if self._active_ref:
            for label in self.query(FootnoteLabel):
                if (label.ref_type, label.ref_name) == self._active_ref:
                    label.set_active(active=False)
                    break

        self._active_ref = (ref_type, ref_name)

        for label in self.query(FootnoteLabel):
            if label.ref_type == ref_type and label.ref_name == ref_name:
                label.set_active(active=True)
                break

        self._rerender_body()

    def clear_highlight(self) -> None:
        """Remove the active reference highlight."""
        if self._active_ref:
            for label in self.query(FootnoteLabel):
                if (label.ref_type, label.ref_name) == self._active_ref:
                    label.set_active(active=False)
                    break
            self._active_ref = None
            self._rerender_body()

    def _rerender_body(self) -> None:
        try:
            md = self.query_one(Markdown)
            md.update(self._build_body())
        except Exception:
            pass

    def on_click(self) -> None:
        """Click on non-link text deselects the active reference."""
        if self._link_clicked:
            self._link_clicked = False
            return
        if self._active_ref:
            self.clear_highlight()

    def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        """Route ref clicks to provenance; open real URLs in browser."""
        self._link_clicked = True
        href = event.href
        if "/" not in href and not href.startswith(("http", "mailto")) and ":" in href:
            ref_type, ref_name = href.split(":", 1)
            self.post_message(ReferenceClicked(ref_type, ref_name))
        else:
            self.app.open_url(href)
