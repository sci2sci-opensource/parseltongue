"""Modal alert shown when history consistency differs from live recomputation."""

from __future__ import annotations

from difflib import SequenceMatcher

from rich import box
from rich.markup import escape as rich_escape
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class ConsistencyAlert(ModalScreen[bool]):
    """Shows cached vs fresh consistency side-by-side with diff highlights.

    Returns True if user chooses to replace, False to keep cached.
    """

    BINDINGS = [
        ("escape", "keep", "Keep"),
        ("left", "select_replace", "Use Current"),
        ("right", "select_keep", "Keep Cached"),
    ]

    DEFAULT_CSS = """
    ConsistencyAlert {
        align: center middle;
    }

    ConsistencyAlert #alert-box {
        width: 90%;
        height: 80%;
        border: heavy $error;
        background: $surface;
        padding: 1 2;
    }

    ConsistencyAlert #alert-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    ConsistencyAlert #diff-scroll {
        height: 1fr;
    }

    ConsistencyAlert #diff-content {
        width: 1fr;
    }

    ConsistencyAlert #alert-buttons {
        height: auto;
        margin-top: 1;
        align: center middle;
    }

    ConsistencyAlert #alert-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, cached: str, fresh: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cached = cached
        self._fresh = fresh

    def compose(self) -> ComposeResult:
        with Vertical(id="alert-box"):
            yield Label("Consistency has changed since this run was saved", id="alert-title")
            with VerticalScroll(id="diff-scroll"):
                yield Static(id="diff-content")
            with Horizontal(id="alert-buttons"):
                yield Button("Use Current", id="replace-btn", variant="warning")
                yield Button("Keep Cached", id="keep-btn", variant="default")

    def on_mount(self) -> None:
        self.query_one("#diff-scroll").can_focus = False
        content = self.query_one("#diff-content", Static)
        content.can_focus = False
        content.update(self._build_table())

    def _build_table(self) -> Table:
        cached_lines = self._cached.splitlines()
        fresh_lines = self._fresh.splitlines()
        sm = SequenceMatcher(None, cached_lines, fresh_lines)

        table = Table(
            expand=True,
            show_header=True,
            show_edge=False,
            pad_edge=False,
            box=box.MINIMAL,
            border_style="dim",
            padding=(0, 1),
        )
        table.add_column("Cached (original)", ratio=1, header_style="bold")
        table.add_column("Current (recomputed)", ratio=1, header_style="bold")

        for op, a0, a1, b0, b1 in sm.get_opcodes():
            if op == "equal":
                for line in cached_lines[a0:a1]:
                    table.add_row(rich_escape(line), rich_escape(line))
            elif op == "replace":
                # Sub-diff within the replace block for better alignment
                _add_replace_rows(table, cached_lines[a0:a1], fresh_lines[b0:b1])
            elif op == "delete":
                for line in cached_lines[a0:a1]:
                    table.add_row(Text(line, style="green"), Text(""))
            elif op == "insert":
                for line in fresh_lines[b0:b1]:
                    table.add_row(Text(""), Text(line, style="red"))

        return table

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "replace-btn":
            self.dismiss(True)
        elif event.button.id == "keep-btn":
            self.dismiss(False)

    def action_keep(self) -> None:
        self.dismiss(False)

    def action_select_keep(self) -> None:
        self.query_one("#keep-btn", Button).focus()

    def action_select_replace(self) -> None:
        self.query_one("#replace-btn", Button).focus()


def _add_replace_rows(table: Table, a_block: list[str], b_block: list[str]) -> None:
    """Add rows for a replace block using sub-diff for better line matching."""
    sub = SequenceMatcher(None, a_block, b_block)
    for op, a0, a1, b0, b1 in sub.get_opcodes():
        if op == "equal":
            for line in a_block[a0:a1]:
                table.add_row(rich_escape(line), rich_escape(line))
        elif op == "replace":
            # 1-to-1 pair with token-level highlight
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


def _line_diff(a: str, b: str) -> tuple[str, str]:
    """Token-level diff within a line pair. Returns (a_markup, b_markup)."""
    # Preserve leading whitespace — .split() strips it
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
