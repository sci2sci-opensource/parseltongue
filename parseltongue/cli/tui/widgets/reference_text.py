"""Reference text widget — markdown with clickable footnote references."""

from __future__ import annotations

import re

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Markdown

TAG_RE = re.compile(r"\[\[(\w+):([^\]]+)\]\]")


class ReferenceClicked(Message):
    """Posted when a [[type:name]] reference is clicked."""

    def __init__(self, ref_type: str, ref_name: str) -> None:
        super().__init__()
        self.ref_type = ref_type
        self.ref_name = ref_name


class ReferenceText(VerticalScroll):
    """Scrollable markdown display with clickable footnote references."""

    def __init__(self, markdown_text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._raw = markdown_text

    def compose(self) -> ComposeResult:
        footnotes: dict[tuple[str, str], int] = {}  # (type, name) -> number

        def _replace_ref(m):
            ref_type, ref_name = m.group(1), m.group(2)
            key = (ref_type, ref_name)
            if key not in footnotes:
                footnotes[key] = len(footnotes) + 1
            num = footnotes[key]
            return f"[\\[{num}\\]]({ref_type}:{ref_name})"

        display_text = TAG_RE.sub(_replace_ref, self._raw)

        # Append footnote list
        if footnotes:
            display_text += "\n\n---\n"
            for (ref_type, ref_name), num in footnotes.items():
                display_text += f"\n[{num}]({ref_type}:{ref_name}) {ref_name}  "

        yield Markdown(display_text, open_links=False)

    def on_markdown_link_clicked(self, event: Markdown.LinkClicked) -> None:
        """Route ref clicks to provenance; open real URLs in browser."""
        href = event.href
        if "/" not in href and not href.startswith(("http", "mailto")) and ":" in href:
            ref_type, ref_name = href.split(":", 1)
            self.post_message(ReferenceClicked(ref_type, ref_name))
        else:
            self.app.open_url(href)
