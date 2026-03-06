"""History browser screen — browse and re-open past pipeline runs."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.screen import Screen
from textual.widgets import DataTable, Label

from ..widgets.hints_bar import HintsBar

_PAGE_SIZE = 50


class RunSelected(Message):
    """Posted when user selects a run to re-open."""

    def __init__(self, run_id: int) -> None:
        super().__init__()
        self.run_id = run_id


class HistoryBrowser(Screen):
    """Table of past runs.  Select one to view cached results."""

    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("delete", "delete_run", "Delete"),
        ("backspace", "delete_run", "Delete"),
    ]

    def compose(self) -> ComposeResult:
        yield Label("Run History", id="history-title")
        yield DataTable(id="history-table")
        yield HintsBar([("Enter", "Open"), ("Del", "Delete", "screen.delete_run"), ("Esc", "Back", "screen.dismiss")])

    def on_mount(self) -> None:
        table = self.query_one("#history-table", DataTable)
        table.add_columns("ID", "Timestamp", "Query", "Model", "Status")
        table.cursor_type = "row"
        self._loaded = 0
        self._exhausted = False
        self._load_more()

    def _load_more(self) -> None:
        if self._exhausted:
            return
        from ...history import list_runs

        runs = list_runs(limit=_PAGE_SIZE, offset=self._loaded)
        if len(runs) < _PAGE_SIZE:
            self._exhausted = True
        if not runs:
            return

        table = self.query_one("#history-table", DataTable)
        for r in runs:
            query_short = r["query"][:60] + "..." if len(r["query"]) > 60 else r["query"]
            table.add_row(
                str(r["id"]),
                r["timestamp"][:19],
                query_short,
                r["model"],
                r["status"],
                key=str(r["id"]),
            )
        self._loaded += len(runs)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if not self._exhausted and event.cursor_row >= self._loaded - 5:
            self._load_more()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = event.row_key
        if row_key and row_key.value is not None:
            self.post_message(RunSelected(int(row_key.value)))

    def action_delete_run(self) -> None:
        table = self.query_one("#history-table", DataTable)
        if table.cursor_row is None:
            return
        try:
            row = table.get_row_at(table.cursor_row)
            run_id = int(row[0])
        except Exception:
            return

        from .confirm import ConfirmModal

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                from ...history import delete_run

                delete_run(run_id)
                self._loaded = 0
                self._exhausted = False
                self._refresh_table()
                self.notify(f"Run {run_id} deleted.")

        self.app.push_screen(ConfirmModal(f"Delete run {run_id}?"), callback=on_confirm)  # type: ignore[arg-type]

    def _refresh_table(self) -> None:
        table = self.query_one("#history-table", DataTable)
        table.clear()
        self._loaded = 0
        self._exhausted = False
        self._load_more()
