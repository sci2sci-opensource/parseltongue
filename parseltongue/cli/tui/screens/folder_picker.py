"""Folder picker screen — browse filesystem, create folders, select a target."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.markup import escape as textual_escape
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, DirectoryTree, Label, Static

from ..widgets.hints_bar import HintsBar


class _FolderTree(DirectoryTree):
    """DirectoryTree that shows only directories (no files)."""

    def filter_paths(self, paths):
        return [p for p in paths if p.is_dir() and not p.name.startswith(".")]


class FolderSelected(Message):
    """Posted when user confirms a folder."""

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self.folder = folder


class FolderPicker(Screen):
    """Pick or create a target folder."""

    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("ctrl+d", "confirm", "Select folder"),
        ("ctrl+n", "create_folder", "New folder"),
        ("ctrl+u", "go_up", "Parent dir"),
    ]

    def __init__(self, root: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._root = root or Path.home()
        self._selected: Path | None = None

    def compose(self) -> ComposeResult:
        with Container(id="folder-picker-panel"):
            with Horizontal(id="folder-picker-header"):
                yield Static(self._breadcrumb(), id="folder-picker-path")
                yield Label("Select target folder", id="folder-picker-hint")
            yield _FolderTree(self._root, id="folder-tree")
            yield Label("", id="folder-picker-selected")
            yield Button("Select this folder", id="folder-pick-btn", variant="primary")
        yield HintsBar(
            [
                ("Enter", "Open"),
                ("Ctrl+N", "New folder", "screen.create_folder"),
                ("Ctrl+U", "Parent dir", "screen.go_up"),
                ("Ctrl+D", "Confirm", "screen.confirm"),
                ("Esc", "Back", "screen.dismiss"),
            ]
        )

    DEFAULT_CSS = """
    FolderPicker { padding: 1 2; }
    FolderPicker #folder-picker-panel { height: 1fr; }
    FolderPicker #folder-picker-header { height: 1; margin-bottom: 1; }
    FolderPicker #folder-picker-path { width: 1fr; height: 1; link-color: cyan; link-style: bold; }
    FolderPicker #folder-picker-hint { width: auto; height: 1; text-style: dim; }
    FolderPicker #folder-tree { height: 1fr; }
    FolderPicker #folder-picker-selected { height: 1; margin-top: 1; }
    FolderPicker #folder-pick-btn { height: auto; }
    """

    def on_mount(self) -> None:
        self.query_one("#folder-tree", _FolderTree).focus()

    def _breadcrumb(self) -> str:
        parts = self._root.parts
        segments = []
        for i, part in enumerate(parts):
            target = str(Path(*parts[: i + 1]))
            escaped = textual_escape(part)
            segments.append(f"[@click=screen.navigate_to('{target}')]" f"[bold cyan]{escaped}[/bold cyan][/]")
        return " / ".join(segments)

    def action_navigate_to(self, target: str) -> None:
        path = Path(target)
        if not path.is_dir() or path == self._root:
            return
        self._root = path
        tree = self.query_one("#folder-tree", _FolderTree)
        tree.path = str(path)
        tree.reload()
        self.query_one("#folder-picker-path", Static).update(self._breadcrumb())

    def action_go_up(self) -> None:
        parent = self._root.parent
        if parent != self._root:
            self.action_navigate_to(str(parent))

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self._selected = Path(event.path)
        self.query_one("#folder-picker-selected", Label).update(f"[bold]Folder:[/bold] {self._selected}")

    def action_confirm(self) -> None:
        folder = self._selected or self._root
        self.post_message(FolderSelected(folder))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "folder-pick-btn":
            self.action_confirm()

    def action_create_folder(self) -> None:
        from .input_modal import InputModal

        parent = self._selected or self._root

        def on_name(name: str | None) -> None:
            if not name or not name.strip():
                return
            new_dir = parent / name.strip()
            try:
                new_dir.mkdir(parents=True, exist_ok=True)
                tree = self.query_one("#folder-tree", _FolderTree)
                tree.reload()
                self._selected = new_dir
                self.query_one("#folder-picker-selected", Label).update(f"[bold]Folder:[/bold] {new_dir}")
                self.notify(f"Created {new_dir.name}/")
            except Exception as exc:
                self.notify(f"Failed: {exc}", severity="error")

        self.app.push_screen(
            InputModal("Folder name:", default=""),
            callback=on_name,
        )
