"""Companion file repair screen — resolve duplicates and misordering.

Launched when the integrity observer detects structural issues in a
companion file.  Maintains a working copy of the companion text that
advances through a sequence of user-confirmed transforms.

Workflow
--------

1.  Screen shows all detected issues based on the **working copy**
    (initially identical to the on-disk companion text).
2.  User clicks an action (e.g. "Repair ordering", "Keep this entry").
3.  The transform is computed against the working copy and a confirm
    modal shows a side-by-side diff (with token-level highlights)
    of the full companion file before and after the change.
4.  On confirm, the working copy advances.  The screen refreshes —
    resolved issues disappear, remaining issues update.
5.  "Apply" writes the final working copy to disk.
6.  "Cancel" discards all changes.

Each confirmed action is a "commit" over the previous working state.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich import box
from rich.markup import escape as rich_escape
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from parseltongue.core.notebooks.companion_integrity import (
    BLOCK_RE,
    build_chain,
    check_corruption,
    check_duplicates,
    check_ordering,
    format_block,
    repair_ordering,
    resolve_duplicates,
)

from ..widgets.diff_table import build_diff_table
from ..widgets.pass_viewer import pv_escape

# ── Data structures ──


@dataclass
class DuplicateEntry:
    """One occurrence of a duplicated block in the companion file."""

    hash: str
    content: str


@dataclass
class DuplicateGroup:
    """All occurrences of a single duplicated block number."""

    block_num: int
    source_content: str
    entries: list[DuplicateEntry]


def collect_duplicates(
    companion_text: str,
    source_blocks: dict[int, str],
) -> list[DuplicateGroup]:
    """Scan companion text and group duplicate entries by block number.

    Parameters
    ----------
    companion_text : str
        Raw companion file content.
    source_blocks : dict[int, str]
        Mapping of pltg block number → source content from the pgmd.

    Returns
    -------
    list[DuplicateGroup]
        Groups with more than one entry, sorted by block number.
    """
    entries: dict[int, list[DuplicateEntry]] = {}
    for m in BLOCK_RE.finditer(companion_text):
        num = int(m.group(1))
        entries.setdefault(num, []).append(DuplicateEntry(hash=m.group(2), content=m.group(3)))
    return [
        DuplicateGroup(
            block_num=num,
            source_content=source_blocks.get(num, ""),
            entries=group,
        )
        for num, group in sorted(entries.items())
        if len(group) > 1
    ]


def _build_entry_table(group: DuplicateGroup) -> Table:
    """Multi-column table: source | entry A | entry B | ...

    Each entry cell is token-level diffed against the source line on that
    row.  Identical lines render plain; changed tokens are highlighted.
    Extra/missing lines show as colored or empty.
    """
    from ..widgets.diff_table import diff_line

    table = Table(
        expand=True,
        show_header=True,
        show_edge=False,
        pad_edge=False,
        box=box.MINIMAL,
        border_style="dim",
        padding=(0, 1),
    )
    table.add_column("Source", ratio=1, header_style="bold cyan")
    for idx, entry in enumerate(group.entries):
        short = entry.hash[:12]
        table.add_column(
            f"Entry {chr(65 + idx)} ({short}...)",
            ratio=1,
            header_style="bold yellow",
        )

    src_lines = group.source_content.splitlines()
    entry_lines = [e.content.splitlines() for e in group.entries]
    max_lines = (
        max(
            len(src_lines),
            *(len(el) for el in entry_lines),
        )
        if entry_lines
        else len(src_lines)
    )

    for i in range(max_lines):
        src_line = src_lines[i] if i < len(src_lines) else ""
        cells: list[Text | str] = [rich_escape(src_line) if src_line else Text("")]
        for el in entry_lines:
            ent_line = el[i] if i < len(el) else ""
            if not src_line and ent_line:
                # Source has no line here — entry has extra
                cells.append(Text(ent_line, style="red"))
            elif src_line and not ent_line:
                # Source has line, entry doesn't
                cells.append(Text(""))
            else:
                cells.append(diff_line(src_line, ent_line))
        table.add_row(*cells)

    return table


# ── Confirm modal (per-action) ──


class RepairConfirmModal(ModalScreen[bool]):
    """Side-by-side diff confirmation for a single repair action.

    Uses Rich Table with token-level highlights, same as ConsistencyAlert.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    RepairConfirmModal {
        align: center middle;
    }

    RepairConfirmModal #rconfirm-box {
        width: 95%;
        height: 90%;
        border: heavy $primary;
        background: $surface;
        padding: 1 2;
    }

    RepairConfirmModal #rconfirm-title {
        text-style: bold;
        margin-bottom: 1;
        height: auto;
    }

    RepairConfirmModal #rconfirm-scroll {
        height: 1fr;
    }

    RepairConfirmModal #rconfirm-buttons {
        height: auto;
        margin-top: 1;
        align: center middle;
    }

    RepairConfirmModal #rconfirm-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, action_label: str, before: str, after: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._action_label = action_label
        self._before = before
        self._after = after

    def compose(self) -> ComposeResult:
        with Vertical(id="rconfirm-box"):
            yield Label(self._action_label, id="rconfirm-title")
            with VerticalScroll(id="rconfirm-scroll"):
                yield Static(id="rconfirm-diff")
            with Horizontal(id="rconfirm-buttons"):
                yield Button("Confirm", id="rconfirm-yes", variant="warning")
                yield Button("Cancel", id="rconfirm-no")

    def on_mount(self) -> None:
        diff = self.query_one("#rconfirm-diff", Static)
        diff.update(build_diff_table(self._before, self._after))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "rconfirm-yes")

    def action_cancel(self) -> None:
        self.dismiss(False)


# ── Main repair screen ──


class CompanionRepairModal(ModalScreen[str | None]):
    """Companion repair screen with commit-based workflow.

    Maintains a working copy of the companion text.  Each user action
    produces a transform, shown in a confirm modal with side-by-side
    token-level diff.  On confirm the working copy advances and the
    screen refreshes.

    Dismisses with the final companion text on "Apply", or None on cancel.

    Parameters
    ----------
    filename : str
        Display name of the pgmd file.
    companion_text : str
        Current companion file content (the initial working copy).
    source_blocks : dict[int, str]
        Mapping of pltg block number → source content from the pgmd.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    CompanionRepairModal {
        align: center middle;
    }

    CompanionRepairModal #repair-box {
        width: 90%;
        height: 90%;
        border: heavy $warning;
        background: $surface;
        padding: 1 2;
    }

    CompanionRepairModal #repair-title {
        text-style: bold;
        margin-bottom: 1;
    }

    CompanionRepairModal #repair-scroll {
        height: 1fr;
    }

    CompanionRepairModal #repair-issues {
        height: auto;
    }

    CompanionRepairModal #corruption-preview {
        height: auto;
        border: solid $primary-darken-2;
    }

    CompanionRepairModal .dup-btn-row {
        height: auto;
        margin-top: 0;
    }

    CompanionRepairModal .dup-btn-spacer {
        width: 1fr;
    }

    CompanionRepairModal .dup-btn {
        width: auto;
        margin: 0 1;
    }

    CompanionRepairModal .dup-btn-col {
        width: 1fr;
        align: center middle;
        height: auto;
    }

    CompanionRepairModal #repair-buttons {
        height: auto;
        margin-top: 1;
        align: center middle;
    }

    CompanionRepairModal #repair-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        filename: str,
        companion_text: str,
        source_blocks: dict[int, str],
        pgmd_source: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._filename = filename
        self._original_text = companion_text
        self._working_text = companion_text
        self._source_blocks = source_blocks
        self._pgmd_source = pgmd_source

    def compose(self) -> ComposeResult:
        with Vertical(id="repair-box"):
            yield Label(
                f"Companion Repair: {self._filename}",
                id="repair-title",
            )
            with VerticalScroll(id="repair-scroll"):
                yield Vertical(id="repair-issues")
            with Horizontal(id="repair-buttons"):
                yield Button("Apply", id="btn-apply", variant="primary", disabled=True)
                yield Button("Cancel", id="btn-cancel")

    def on_mount(self) -> None:
        self._refresh_issues()

    def _refresh_issues(self) -> None:
        """Rebuild the issues display from the current working copy."""
        container = self.query_one("#repair-issues", Vertical)
        container.remove_children()

        # Enable Apply only when working copy differs from original
        try:
            apply_btn = self.query_one("#btn-apply", Button)
            apply_btn.disabled = self._working_text == self._original_text
        except Exception:
            pass

        corrupted = check_corruption(self._working_text)
        misordered = check_ordering(self._working_text)
        duplicates = check_duplicates(self._working_text)
        groups = collect_duplicates(self._working_text, self._source_blocks)

        widgets: list = []

        if not corrupted and not misordered and not duplicates:
            if self._working_text != self._original_text:
                widgets.append(Static("[bold green]All issues resolved.[/bold green] " "Press Apply to save."))
            else:
                widgets.append(Static("[dim]No structural issues found.[/dim]"))
            container.mount_all(widgets)
            return

        # Corruption
        if corrupted:
            markers = list(BLOCK_RE.finditer(self._working_text))
            if not markers:
                desc = "No block markers found — file contains raw code without structure."
            else:
                desc = "Content found outside block markers."
            preview = self._working_text
            widgets.append(Static(f"[bold red]⚠ Corrupted companion file[/bold red]\n" f"  {desc}"))
            widgets.append(Static(f"[dim]{pv_escape(preview)}[/dim]", id="corruption-preview"))
            widgets.append(Button("Overwrite with source blocks", id="btn-overwrite", variant="warning"))

        # Misordering
        if misordered:
            current_order: list[int] = []
            for m in BLOCK_RE.finditer(self._working_text):
                current_order.append(int(m.group(1)))
            expected = sorted(current_order)
            widgets.append(
                Static(
                    f"[bold yellow]⚠ Blocks out of order[/bold yellow]\n"
                    f"  Current:  {current_order}\n"
                    f"  Expected: {expected}"
                )
            )
            widgets.append(Button("Repair ordering", id="btn-reorder", variant="warning"))

        # Duplicates — one diff table per entry, each with its own keep button
        for group in groups:
            n = group.block_num
            count = len(group.entries)
            summary = ""
            for line in group.source_content.splitlines():
                s = line.strip()
                if s and not s.startswith(";;"):
                    summary = s[:60]
                    break
            widgets.append(
                Static(
                    f"\n[bold yellow]⚠ Block {n}[/bold yellow] — "
                    f"{count} entries — "
                    f"source: [dim]{pv_escape(summary)}[/dim]"
                )
            )

            # Single multi-column table with token-level highlights
            table_widget = Static(id=f"dup-table-{n}")
            widgets.append(table_widget)

            # Keep buttons aligned under their columns
            btn_row: list = [Static("", classes="dup-btn-spacer")]  # spacer for Source col
            for idx, entry in enumerate(group.entries):
                short = entry.hash[:12]
                btn_row.append(
                    Horizontal(
                        Button(
                            f"Keep {chr(65 + idx)} ({short}...)",
                            id=f"keep-{n}-{idx}",
                            variant="primary",
                            classes="dup-btn",
                        ),
                        classes="dup-btn-col",
                    )
                )
            widgets.append(Horizontal(*btn_row, classes="dup-btn-row"))

        container.mount_all(widgets)

        # Populate tables after mount
        for group in groups:
            try:
                tw = self.query_one(f"#dup-table-{group.block_num}", Static)
                tw.update(_build_entry_table(group))
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        btn_id = event.button.id
        if not btn_id:
            return

        if btn_id == "btn-overwrite":
            self._do_overwrite()
            return

        if btn_id == "btn-reorder":
            self._do_reorder()
            return

        if btn_id.startswith("keep-"):
            parts = btn_id.split("-")
            block_num = int(parts[1])
            entry_idx = int(parts[2])
            self._do_keep(block_num, entry_idx)
            return

        if btn_id == "btn-apply":
            if self._working_text != self._original_text:
                self.dismiss(self._working_text)
            else:
                self.dismiss(None)
            return

        if btn_id == "btn-cancel":
            self.dismiss(None)

    def _do_reorder(self) -> None:
        """Compute reorder transform and show confirm with diff."""
        new_text = repair_ordering(self._working_text)
        if new_text == self._working_text:
            return

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self._working_text = new_text
                self._refresh_issues()

        self.app.push_screen(
            RepairConfirmModal(
                action_label="Repair block ordering",
                before=self._working_text,
                after=new_text,
            ),
            callback=_on_confirm,
        )

    def _do_overwrite(self) -> None:
        """Rebuild companion from source blocks and show confirm with diff."""
        if not self._pgmd_source:
            return
        chain = build_chain(self._pgmd_source)
        parts = []
        for bn in sorted(self._source_blocks):
            h = chain[bn] if bn < len(chain) else ""
            if h:
                parts.append(format_block(bn, self._source_blocks[bn], h))
        new_text = "\n".join(parts) + "\n" if parts else ""

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self._working_text = new_text
                self._refresh_issues()

        self.app.push_screen(
            RepairConfirmModal(
                action_label="Overwrite companion with source blocks",
                before=self._working_text,
                after=new_text,
            ),
            callback=_on_confirm,
        )

    def _do_keep(self, block_num: int, entry_idx: int) -> None:
        """Compute dedup transform and show confirm with diff."""
        groups = collect_duplicates(self._working_text, self._source_blocks)
        target = None
        for g in groups:
            if g.block_num == block_num:
                target = g
                break
        if target is None or entry_idx >= len(target.entries):
            return

        canonical_hash = target.entries[entry_idx].hash
        new_text = resolve_duplicates(self._working_text, block_num, canonical_hash)
        if new_text == self._working_text:
            return

        short = canonical_hash[:12]

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self._working_text = new_text
                self._refresh_issues()

        self.app.push_screen(
            RepairConfirmModal(
                action_label=f"Block {block_num}: keep entry {short}..., remove duplicates",
                before=self._working_text,
                after=new_text,
            ),
            callback=_on_confirm,
        )

    def action_cancel(self) -> None:
        self.dismiss(None)
