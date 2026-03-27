"""Parseltongue Markdown (.pgmd) parser.

PGMD files are Markdown with embedded Parseltongue code blocks,
like Jupyter notebooks for pltg.  Code blocks are fenced with
``scheme`` language tag and annotated with ``;; pltg`` on the first
line.  Non-annotated scheme blocks are display-only.

Inline references
-----------------

Prose sections can reference nodes defined in pltg blocks using
``[[type:name]]`` syntax.  The renderer resolves these to values
from the loaded system.

    [[fact:revenue]]        → value shown inline + footnote number
    [[term:gross-margin]]   → same, for derived terms
    [[~fact:revenue]]       → silent footnote (number only, no inline value)

The ``~`` prefix produces a silent ref: only a superscript footnote
number appears in the prose, but the node still shows in the margin
pill cluster and the footnote list below the paragraph.

Example::

    # My Analysis

    Revenue analysis with [[fact:revenue]] reference.
    Strong unit economics[[~term:ltv-to-cac]] support the thesis.

    ```scheme
    ;; pltg
    (load-document "Report" "resources/report.txt")
    (fact revenue 15 :origin "Q3 report")
    ```

    More prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_FENCE_RE = re.compile(
    r"^```(\w*)\s*$\n(.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)

_PLTG_MARKER = re.compile(r"^\s*;;\s*pltg(?:\s+(.+?))?\s*$", re.MULTILINE)


@dataclass
class PgmdBlock:
    """A single block in a .pgmd file."""

    kind: Literal["prose", "pltg", "code"]
    content: str
    start_line: int
    title: str | None = None  # optional name from ";; pltg My Title"
    language: str = ""  # fence language tag (e.g. "scheme", "", "python")


def parse_pgmd(text: str) -> list[PgmdBlock]:
    """Parse a .pgmd file into typed blocks.

    Returns a list of PgmdBlock in document order:
    - ``prose``: markdown text between code fences
    - ``pltg``: executable parseltongue (scheme block with ;; pltg marker)
    - ``code``: non-executable code block (scheme without marker, or other language)
    """
    blocks: list[PgmdBlock] = []
    last_end = 0

    for m in _FENCE_RE.finditer(text):
        # Prose before this fence
        if m.start() > last_end:
            prose = text[last_end : m.start()]
            if prose.strip():
                line = text[:last_end].count("\n") + 1
                blocks.append(PgmdBlock(kind="prose", content=prose, start_line=line))

        lang = m.group(1).lower()
        body = m.group(2)
        fence_line = text[: m.start()].count("\n") + 1

        marker_m = _PLTG_MARKER.match(body)
        if lang == "scheme" and marker_m:
            title = marker_m.group(1)  # None when ";; pltg" alone
            blocks.append(PgmdBlock(kind="pltg", content=body, start_line=fence_line, title=title, language="scheme"))
        else:
            blocks.append(PgmdBlock(kind="code", content=body, start_line=fence_line, language=lang))

        last_end = m.end()

    # Trailing prose
    if last_end < len(text):
        trailing = text[last_end:]
        if trailing.strip():
            line = text[:last_end].count("\n") + 1
            blocks.append(PgmdBlock(kind="prose", content=trailing, start_line=line))

    return blocks


def extract_pltg(text: str) -> str:
    """Extract concatenated pltg source from all executable blocks."""
    parts = [b.content for b in parse_pgmd(text) if b.kind == "pltg"]
    return "\n\n".join(parts)


# ── Inline reference helpers ──

_REF_RE = re.compile(r"\[\[(~?)(\w+):([^\]]+)\]\]")


@dataclass
class PgmdRef:
    """An inline reference found in prose."""

    name: str
    ref_type: str  # "fact", "term", "axiom", etc.
    silent: bool  # True when prefixed with ~
    start: int  # char offset in source text
    end: int


def extract_refs(text: str) -> list[PgmdRef]:
    """Extract all inline ``[[type:name]]`` / ``[[~type:name]]`` refs from text."""
    return [
        PgmdRef(
            name=m.group(3),
            ref_type=m.group(2),
            silent=bool(m.group(1)),
            start=m.start(),
            end=m.end(),
        )
        for m in _REF_RE.finditer(text)
    ]


def ref_names(text: str) -> set[str]:
    """Return the set of node names referenced in text."""
    return {r.name for r in extract_refs(text)}
