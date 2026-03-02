"""Document picker screen — file browser with multi-select."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, DirectoryTree, Label, ListItem, ListView


class DocumentsSelected(Message):
    """Posted when user confirms document selection."""

    def __init__(self, paths: list[Path]) -> None:
        super().__init__()
        self.paths = paths


class DocumentPicker(Screen):
    """File browser rooted at CWD.  Select files/dirs, accumulate in hopper."""

    BINDINGS = [
        ("backspace", "remove_selected", "Remove"),
        ("delete", "remove_selected", "Remove"),
        ("ctrl+d", "confirm", "Done"),
    ]

    def __init__(self, root: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._root = root or Path.cwd()
        self._selected: list[Path] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="picker-layout"):
            with Container(id="browser-panel"):
                yield Label("Space: expand/collapse  Enter: add", id="browser-label")
                yield DirectoryTree(str(self._root), id="file-tree")
            with Container(id="selected-panel"):
                yield Label("Selected documents:", id="selected-label")
                yield ListView(id="selected-list")
                yield Button("Continue", id="continue-btn", variant="primary")

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Add file to selected list."""
        path = Path(event.path)
        if path not in self._selected:
            self._selected.append(path)
            self._refresh_list()

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        """Add all direct child files from directory."""
        dir_path = Path(event.path)
        for child in sorted(dir_path.iterdir()):
            if child.is_file() and child not in self._selected:
                self._selected.append(child)
        self._refresh_list()

    def action_remove_selected(self) -> None:
        """Remove the currently highlighted item in the selected list."""
        lv = self.query_one("#selected-list", ListView)
        idx = lv.index
        if idx is not None and 0 <= idx < len(self._selected):
            self._selected.pop(idx)
            self._refresh_list()
        elif self._selected:
            # Fallback: remove last if nothing highlighted
            self._selected.pop()
            self._refresh_list()

    def action_confirm(self) -> None:
        self._emit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "continue-btn":
            self._emit()

    def _emit(self) -> None:
        if not self._selected:
            self.notify("Select at least one document.", severity="warning")
            return
        self.post_message(DocumentsSelected(list(self._selected)))

    def _refresh_list(self) -> None:
        lv = self.query_one("#selected-list", ListView)
        lv.clear()
        for p in self._selected:
            lv.append(ListItem(Label(str(p.name))))
