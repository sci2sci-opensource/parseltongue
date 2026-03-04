"""Document picker screen — file browser with multi-select."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.markup import escape as textual_escape
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, DirectoryTree, Label, ListItem, ListView, Static

from ..widgets.hints_bar import HintsBar

if TYPE_CHECKING:
    from textual.timer import Timer


class DocumentsSelected(Message):
    """Posted when user confirms document selection with ingested texts."""

    def __init__(self, paths: list[Path], ingested: dict[str, str]) -> None:
        super().__init__()
        self.paths = paths
        self.ingested = ingested


class DocumentPicker(Screen):
    """File browser rooted at CWD.  Select files/dirs, accumulate in hopper."""

    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("backspace", "remove_selected", "Remove"),
        ("delete", "remove_selected", "Remove"),
        ("ctrl+d", "confirm", "Done"),
        ("ctrl+u", "go_up", "Parent dir"),
    ]

    _SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, root: Path | None = None, selected: list[Path] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._root = root or Path.cwd()
        self._selected: list[Path] = list(selected) if selected else []
        self._errors: dict[Path, str] = {}
        self._ingesting = False
        self._current_file = ""
        self._spinner_timer: Timer | None = None
        self._spinner_idx = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="picker-layout"):
            with Container(id="browser-panel"):
                with Horizontal(id="browser-header"):
                    yield Static(self._build_breadcrumb(), id="browser-path")
                    yield Label("Space: expand/collapse  Enter: add", id="browser-label")
                yield DirectoryTree(str(self._root), id="file-tree")
            with Container(id="selected-panel"):
                yield Label("Selected documents:", id="selected-label")
                yield ListView(id="selected-list")
                yield Label("", id="ingest-status")
                yield Button("Continue", id="continue-btn", variant="primary")
        yield HintsBar(
            [
                ("Enter", "Add"),
                ("Backspace", "Remove selected"),
                ("Ctrl+U", "Parent dir", "screen.go_up"),
                ("Ctrl+D", "Done", "screen.confirm"),
                ("Esc", "Back", "screen.dismiss"),
            ]
        )

    def on_mount(self) -> None:
        if self._selected:
            self._refresh_list()

    def _build_breadcrumb(self) -> str:
        """Build clickable path breadcrumb: / > Users > v_work > ..."""
        parts = self._root.parts
        segments = []
        for i, part in enumerate(parts):
            target = str(Path(*parts[: i + 1]))
            escaped = textual_escape(part)
            segments.append(f"[@click=screen.navigate_to('{target}')][bold cyan]{escaped}[/bold cyan][/]")
        return " / ".join(segments)

    def _navigate_to(self, target: str) -> None:
        """Navigate the tree to a specific directory."""
        path = Path(target)
        if not path.is_dir() or path == self._root:
            return
        self._root = path
        tree = self.query_one("#file-tree", DirectoryTree)
        tree.path = str(path)
        tree.reload()
        self.query_one("#browser-path", Static).update(self._build_breadcrumb())

    def action_navigate_to(self, target: str) -> None:
        self._navigate_to(target)

    def action_go_up(self) -> None:
        parent = self._root.parent
        if parent != self._root:
            self._navigate_to(str(parent))

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Add file to selected list."""
        path = Path(event.path)
        if path not in self._selected:
            self._selected.append(path)
            self._errors.pop(path, None)
            self._refresh_list()

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        pass

    def action_remove_selected(self) -> None:
        """Remove the currently highlighted item in the selected list."""
        lv = self.query_one("#selected-list", ListView)
        idx = lv.index
        if idx is not None and 0 <= idx < len(self._selected):
            self._selected.pop(idx)
            self._refresh_list()
        elif self._selected:
            self._selected.pop()
            self._refresh_list()

    def action_confirm(self) -> None:
        self._start_ingest()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue-btn":
            self._start_ingest()

    # ------------------------------------------------------------------
    # Spinner — same pattern as LivePassScreen (set_interval + async worker)
    # ------------------------------------------------------------------

    def _start_spinner(self) -> None:
        self._spinner_idx = 0
        self._spinner_timer = self.set_interval(0.1, self._tick_spinner)

    def _tick_spinner(self) -> None:
        frame = self._SPINNER[self._spinner_idx % len(self._SPINNER)]
        self._spinner_idx += 1
        suffix = f" {self._current_file}" if self._current_file else ""
        self.query_one("#ingest-status", Label).update(f"{frame} Ingesting{suffix}...")

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None

    # ------------------------------------------------------------------
    # Ingestion — async worker with asyncio.to_thread (same as live_pass)
    # ------------------------------------------------------------------

    def _start_ingest(self) -> None:
        if not self._selected:
            self.notify("Select at least one document.", severity="warning")
            return
        if self._ingesting:
            return
        self._ingesting = True
        self._errors.clear()
        self.query_one("#continue-btn", Button).disabled = True
        self._start_spinner()
        self.run_worker(self._do_ingest(), exclusive=True)

    async def _do_ingest(self) -> None:
        """Async worker — matches LivePassScreen._execute_current_pass pattern."""
        from ...ingest import ingest_file

        ingested: dict[str, str] = {}
        errors: dict[Path, str] = {}

        for p in self._selected:
            self._current_file = p.name
            try:
                text = await asyncio.to_thread(ingest_file, str(p))
                ingested[p.stem] = text
            except Exception as exc:
                errors[p] = str(exc)

        self._current_file = ""
        self._stop_spinner()
        self._ingesting = False

        try:
            self.query_one("#ingest-status", Label).update("")
            self.query_one("#continue-btn", Button).disabled = False
        except Exception:
            pass

        if errors:
            self._errors = errors
            self._refresh_list()
            for p, err in errors.items():
                self.notify(f"{p.name}: {err}", severity="error", timeout=10)
        else:
            self.post_message(DocumentsSelected(list(self._selected), ingested))

    def _refresh_list(self) -> None:
        lv = self.query_one("#selected-list", ListView)
        lv.clear()
        for p in self._selected:
            err = self._errors.get(p)
            if err:
                lv.append(ListItem(Label(f"[red]{p.name}  ✗ {err}[/red]")))
            else:
                lv.append(ListItem(Label(str(p.name))))
