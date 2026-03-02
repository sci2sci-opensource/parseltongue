"""History browser screen — browse and re-open past pipeline runs."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.screen import Screen
from textual.widgets import DataTable, Label

from ..widgets.hints_bar import HintsBar


class RunSelected(Message):
    """Posted when user selects a run to re-open."""

    def __init__(self, run_id: int) -> None:
        super().__init__()
        self.run_id = run_id


class HistoryBrowser(Screen):
    """Table of past runs.  Select one to view cached results."""

    BINDINGS = [
        ("escape", "dismiss", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Label("Run History", id="history-title")
        yield DataTable(id="history-table")
        yield HintsBar([("Enter", "Open"), ("Esc", "Back")])

    def on_mount(self) -> None:
        from ...history import list_runs

        table = self.query_one("#history-table", DataTable)
        table.add_columns("ID", "Timestamp", "Query", "Model", "Status")
        table.cursor_type = "row"

        runs = list_runs()
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

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = event.row_key
        if row_key and row_key.value is not None:
            self.post_message(RunSelected(int(row_key.value)))
