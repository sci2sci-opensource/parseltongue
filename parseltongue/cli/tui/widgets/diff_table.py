"""Shared side-by-side diff rendering with token-level highlights.

Used by ConsistencyAlert, CompanionRepairModal, and ViewerScreen
for all diff displays.  Single implementation, one algorithm.

All functions are pure — they take strings, return Rich renderables.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from rich import box
from rich.markup import escape as rich_escape
from rich.table import Table
from rich.text import Text


def build_diff_table(
    before: str,
    after: str,
    col_a: str = "Before",
    col_b: str = "After",
) -> Table:
    """Side-by-side diff table with token-level highlights.

    Parameters
    ----------
    before : str
        Left-side text (old / cached / companion).
    after : str
        Right-side text (new / fresh / source).
    col_a, col_b : str
        Column header labels.

    Returns
    -------
    Table
        Rich Table ready to render.
    """
    a_lines = before.splitlines()
    b_lines = after.splitlines()
    sm = SequenceMatcher(None, a_lines, b_lines, autojunk=False)

    table = Table(
        expand=True,
        show_header=True,
        show_edge=False,
        pad_edge=False,
        box=box.MINIMAL,
        border_style="dim",
        padding=(0, 1),
    )
    table.add_column(col_a, ratio=1, header_style="bold")
    table.add_column(col_b, ratio=1, header_style="bold")

    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == "equal":
            for line in a_lines[a0:a1]:
                table.add_row(rich_escape(line), rich_escape(line))
        elif op == "replace":
            _add_replace_rows(table, a_lines[a0:a1], b_lines[b0:b1])
        elif op == "delete":
            for line in a_lines[a0:a1]:
                table.add_row(Text(line, style="green"), Text(""))
        elif op == "insert":
            for line in b_lines[b0:b1]:
                table.add_row(Text(""), Text(line, style="red"))

    return table


def _add_replace_rows(
    table: Table,
    a_block: list[str],
    b_block: list[str],
) -> None:
    """Add rows for a replace block with sub-diff for line alignment."""
    sub = SequenceMatcher(None, a_block, b_block, autojunk=False)
    for op, a0, a1, b0, b1 in sub.get_opcodes():
        if op == "equal":
            for line in a_block[a0:a1]:
                table.add_row(rich_escape(line), rich_escape(line))
        elif op == "replace":
            paired = min(a1 - a0, b1 - b0)
            for i in range(paired):
                a_hl, b_hl = _line_diff(a_block[a0 + i], b_block[b0 + i])
                table.add_row(Text.from_markup(a_hl), Text.from_markup(b_hl))
            for line in a_block[a0 + paired : a1]:
                table.add_row(Text(line, style="green"), Text(""))
            for line in b_block[b0 + paired : b1]:
                table.add_row(Text(""), Text(line, style="red"))
        elif op == "delete":
            for line in a_block[a0:a1]:
                table.add_row(Text(line, style="green"), Text(""))
        elif op == "insert":
            for line in b_block[b0:b1]:
                table.add_row(Text(""), Text(line, style="red"))


def diff_line(reference: str, candidate: str) -> Text:
    """Highlight a candidate line against a reference using token-level diff.

    Returns a Rich Text with changed tokens highlighted.  Unchanged lines
    return plain escaped text.  Use this for multi-column tables where each
    cell is diffed against a shared reference.
    """
    if reference == candidate:
        return Text(rich_escape(candidate))
    _, markup = _line_diff(reference, candidate)
    return Text.from_markup(markup)


def _line_diff(a: str, b: str) -> tuple[str, str]:
    """Token-level diff within a line pair. Returns (a_markup, b_markup)."""
    a_indent = len(a) - len(a.lstrip())
    b_indent = len(b) - len(b.lstrip())
    a_tokens = a.split()
    b_tokens = b.split()
    sm = SequenceMatcher(None, a_tokens, b_tokens)
    a_parts: list[str] = []
    b_parts: list[str] = []
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == "equal":
            a_parts.extend(rich_escape(t) for t in a_tokens[a0:a1])
            b_parts.extend(rich_escape(t) for t in b_tokens[b0:b1])
        elif op == "replace":
            a_parts.extend(f"[green]{rich_escape(t)}[/green]" for t in a_tokens[a0:a1])
            b_parts.extend(f"[red]{rich_escape(t)}[/red]" for t in b_tokens[b0:b1])
        elif op == "delete":
            a_parts.extend(f"[green]{rich_escape(t)}[/green]" for t in a_tokens[a0:a1])
        elif op == "insert":
            b_parts.extend(f"[red]{rich_escape(t)}[/red]" for t in b_tokens[b0:b1])
    return " " * a_indent + " ".join(a_parts), " " * b_indent + " ".join(b_parts)
