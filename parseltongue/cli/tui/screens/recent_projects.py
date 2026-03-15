"""Recent projects screen — browse and re-open saved projects."""

from __future__ import annotations

import json
from pathlib import Path

from textual.app import ComposeResult
from textual.message import Message
from textual.screen import Screen
from textual.widgets import DataTable, Label

from ..widgets.hints_bar import HintsBar


class ProjectOpenRequested(Message):
    """Posted when user selects a project to re-open."""

    def __init__(
        self, project_dir: Path, entry_point: Path, open_files: list[Path], project_id: int | None = None
    ) -> None:
        super().__init__()
        self.project_dir = project_dir
        self.entry_point = entry_point
        self.open_files = open_files
        self.project_id = project_id


class RecentProjects(Screen):
    """Table of saved projects. Select one to re-open."""

    BINDINGS = [
        ("escape", "app.main_menu", "Back"),
        ("delete", "delete_project", "Delete"),
        ("backspace", "delete_project", "Delete"),
    ]

    def compose(self) -> ComposeResult:
        yield Label("Recent Projects", id="recent-projects-title")
        yield DataTable(id="recent-projects-table")
        yield HintsBar(
            [
                ("Enter", "Open"),
                ("Del", "Delete", "screen.delete_project"),
                ("Esc", "Menu", "app.main_menu"),
            ]
        )

    def on_mount(self) -> None:
        table = self.query_one("#recent-projects-table", DataTable)
        table.add_columns("Name", "Entry point", "Last opened")
        table.cursor_type = "row"
        self._load()

    def _load(self) -> None:
        from ...history import list_projects

        self._projects = list_projects()
        table = self.query_one("#recent-projects-table", DataTable)
        table.clear()
        for p in self._projects:
            table.add_row(
                p["name"],
                Path(p["entry_point"]).name,
                p["last_opened"][:19],
                key=str(p["id"]),
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = event.row_key
        if not row_key or row_key.value is None:
            return
        project_id = int(row_key.value)
        project = next((p for p in self._projects if p["id"] == project_id), None)
        if not project:
            return

        project_dir = Path(project["project_dir"])
        entry_point = Path(project["entry_point"])

        if not project_dir.is_dir():
            self.notify(f"Directory not found: {project_dir}", severity="error")
            return
        if not entry_point.is_file():
            self.notify(f"Entry point not found: {entry_point}", severity="error")
            return

        open_files = [Path(f) for f in json.loads(project.get("open_files", "[]"))]
        self.post_message(ProjectOpenRequested(project_dir, entry_point, open_files, project_id=project_id))

    def action_delete_project(self) -> None:
        table = self.query_one("#recent-projects-table", DataTable)
        if table.cursor_row is None:
            return
        try:
            from textual.coordinate import Coordinate

            row_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key
            project_id = int(row_key.value)  # type: ignore[arg-type]
        except Exception:
            return

        from .confirm import ConfirmModal

        name = next(
            (p["name"] for p in self._projects if p["id"] == project_id),
            "?",
        )

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                from ...history import delete_project

                delete_project(project_id)
                self._load()
                self.notify(f"Project '{name}' removed.")

        self.app.push_screen(
            ConfirmModal(f"Remove '{name}' from recent projects?"),
            callback=on_confirm,  # type: ignore[arg-type]
        )
