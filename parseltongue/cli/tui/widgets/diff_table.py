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


def build_unified_diff_table(
    before: str,
    after: str,
    filepath: str = "",
    context: int = 3,
) -> Table:
    """Unified (merged) diff table with line numbers and context.

    Shows context lines around changes, with ``-`` / ``+`` gutter markers
    and line numbers from both sides.
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
        title=f"[dim]{rich_escape(filepath)}[/dim]" if filepath else None,
        title_style="dim",
    )
    table.add_column("", width=4, style="dim", justify="right")  # old line no
    table.add_column("", width=4, style="dim", justify="right")  # new line no
    table.add_column("", width=1, style="dim")  # gutter +/-/
    table.add_column("", ratio=1)  # content

    # Collect all hunks with context
    opcodes = sm.get_opcodes()
    rows: list[tuple[str, str, str | Text, str | Text]] = []

    for idx, (op, a0, a1, b0, b1) in enumerate(opcodes):
        if op == "equal":
            lines = a_lines[a0:a1]
            if len(lines) <= context * 2 + 1:
                # Short enough to show all
                for i, line in enumerate(lines):
                    rows.append(
                        (
                            str(a0 + i + 1),
                            str(b0 + i + 1),
                            " ",
                            rich_escape(line),
                        )
                    )
            else:
                # Leading context
                for i in range(min(context, len(lines))):
                    rows.append(
                        (
                            str(a0 + i + 1),
                            str(b0 + i + 1),
                            " ",
                            rich_escape(lines[i]),
                        )
                    )
                if len(lines) > context * 2:
                    rows.append(("", "", "", Text("···", style="dim")))
                # Trailing context
                trail = max(context, 0)
                for i in range(max(0, len(lines) - trail), len(lines)):
                    rows.append(
                        (
                            str(a0 + i + 1),
                            str(b0 + i + 1),
                            " ",
                            rich_escape(lines[i]),
                        )
                    )

        elif op == "replace":
            # Show removed lines
            for i, line in enumerate(a_lines[a0:a1]):
                a_hl, _ = _line_diff(line, "")
                rows.append(
                    (
                        str(a0 + i + 1),
                        "",
                        Text("-", style="bold red"),
                        Text(line, style="red"),
                    )
                )
            # Show added lines
            for i, line in enumerate(b_lines[b0:b1]):
                rows.append(
                    (
                        "",
                        str(b0 + i + 1),
                        Text("+", style="bold green"),
                        Text(line, style="green"),
                    )
                )
        elif op == "delete":
            for i, line in enumerate(a_lines[a0:a1]):
                rows.append(
                    (
                        str(a0 + i + 1),
                        "",
                        Text("-", style="bold red"),
                        Text(line, style="red"),
                    )
                )
        elif op == "insert":
            for i, line in enumerate(b_lines[b0:b1]):
                rows.append(
                    (
                        "",
                        str(b0 + i + 1),
                        Text("+", style="bold green"),
                        Text(line, style="green"),
                    )
                )

    for r in rows:
        table.add_row(*r)

    return table


def build_split_diff_table(
    before: str,
    after: str,
    filepath: str = "",
    context: int = 3,
) -> Table:
    """Side-by-side diff table with line numbers and context.

    Wraps :func:`build_diff_table` but adds line number columns.
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
        title=f"[dim]{rich_escape(filepath)}[/dim]" if filepath else None,
        title_style="dim",
    )
    table.add_column("", width=4, style="dim", justify="right")  # old lineno
    table.add_column("Old", ratio=1, header_style="bold red")
    table.add_column("", width=4, style="dim", justify="right")  # new lineno
    table.add_column("New", ratio=1, header_style="bold green")

    opcodes = sm.get_opcodes()

    for idx, (op, a0, a1, b0, b1) in enumerate(opcodes):
        if op == "equal":
            lines = a_lines[a0:a1]
            if len(lines) <= context * 2 + 1:
                for i, line in enumerate(lines):
                    esc = rich_escape(line)
                    table.add_row(str(a0 + i + 1), esc, str(b0 + i + 1), esc)
            else:
                for i in range(min(context, len(lines))):
                    esc = rich_escape(lines[i])
                    table.add_row(str(a0 + i + 1), esc, str(b0 + i + 1), esc)
                table.add_row("", Text("···", style="dim"), "", Text("···", style="dim"))
                for i in range(max(0, len(lines) - context), len(lines)):
                    esc = rich_escape(lines[i])
                    table.add_row(str(a0 + i + 1), esc, str(b0 + i + 1), esc)
        elif op == "replace":
            paired = min(a1 - a0, b1 - b0)
            for i in range(paired):
                a_hl, b_hl = _line_diff(a_lines[a0 + i], b_lines[b0 + i])
                table.add_row(
                    str(a0 + i + 1),
                    Text.from_markup(a_hl),
                    str(b0 + i + 1),
                    Text.from_markup(b_hl),
                )
            for i in range(paired, a1 - a0):
                table.add_row(
                    str(a0 + i + 1),
                    Text(a_lines[a0 + i], style="red"),
                    "",
                    Text(""),
                )
            for i in range(paired, b1 - b0):
                table.add_row(
                    "",
                    Text(""),
                    str(b0 + i + 1),
                    Text(b_lines[b0 + i], style="green"),
                )
        elif op == "delete":
            for i, line in enumerate(a_lines[a0:a1]):
                table.add_row(str(a0 + i + 1), Text(line, style="red"), "", Text(""))
        elif op == "insert":
            for i, line in enumerate(b_lines[b0:b1]):
                table.add_row("", Text(""), str(b0 + i + 1), Text(line, style="green"))

    return table


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
            a_parts.extend(f"[bold red]{rich_escape(t)}[/bold red]" for t in a_tokens[a0:a1])
            b_parts.extend(f"[bold green]{rich_escape(t)}[/bold green]" for t in b_tokens[b0:b1])
        elif op == "delete":
            a_parts.extend(f"[bold red]{rich_escape(t)}[/bold red]" for t in a_tokens[a0:a1])
        elif op == "insert":
            b_parts.extend(f"[bold green]{rich_escape(t)}[/bold green]" for t in b_tokens[b0:b1])
    return " " * a_indent + " ".join(a_parts), " " * b_indent + " ".join(b_parts)
