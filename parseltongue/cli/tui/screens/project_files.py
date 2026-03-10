"""Project files screen — file browser for .pltg projects.

Used in two modes:
1. **Picker mode** — initial project setup: select entry point file, posts
   ProjectSelected when confirmed.
2. **Browser mode** — after project is loaded: browse files, open in editor.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.markup import escape as textual_escape
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, DirectoryTree, Label, Static

from ..widgets.hints_bar import HintsBar


class ProjectTree(DirectoryTree):
    """DirectoryTree showing all files in the project."""

    def filter_paths(self, paths):
        # Show everything except hidden files/dirs
        return [p for p in paths if not p.name.startswith(".")]


class ProjectSelected(Message):
    """Posted when user picks an entry point file (picker mode)."""

    def __init__(self, entry_point: Path, project_dir: Path) -> None:
        super().__init__()
        self.entry_point = entry_point
        self.project_dir = project_dir


class FileOpenRequested(Message):
    """Posted when a file is selected for editing (browser mode)."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path


class ProjectFilesScreen(Screen):
    """Browse the filesystem and select a .pltg/.pgmd entry point.

    In picker mode (no project loaded yet), selecting a file sets it as
    the entry point candidate.  Press Ctrl+D or the Open button to confirm.

    In browser mode (project already loaded), selecting a file opens it
    in the editor.
    """

    BINDINGS = [
        ("f1", "app.switch_screen('editor')", "Editor"),
        ("f2", "app.switch_screen('viewer')", "Viewer"),
        ("f3", "app.switch_screen('modules')", "Modules"),
        ("f4", "app.switch_screen('system_state')", "System"),
        ("f5", "app.switch_screen('consistency')", "Consistency"),
        ("f6", "app.switch_screen('project_files')", "Files"),
        ("f7", "app.main_menu", "Menu"),
        ("escape", "app.project_selector", "Projects"),
        ("ctrl+d", "confirm", "Open project"),
        ("ctrl+e", "set_entry_from_tree", "Set entry"),
        ("ctrl+u", "go_up", "Parent dir"),
    ]

    def __init__(
        self,
        root: Path | None = None,
        *,
        picker_mode: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._root = root or Path.cwd()
        self._picker_mode = picker_mode
        self._picker_step: int = 1 if picker_mode else 0  # 1=pick folder, 2=pick entry
        self._project_dir: Path | None = None
        self._selected_entry: Path | None = None

    def compose(self) -> ComposeResult:
        with Container(id="project-files-panel"):
            with Horizontal(id="project-files-header"):
                yield Static(self._build_breadcrumb(), id="project-path")
                if self._picker_mode:
                    yield Label(
                        "Step 1: Select project folder",
                        id="project-files-hint",
                    )
            yield ProjectTree(self._root, id="project-tree")
            if self._picker_mode:
                yield Label("", id="project-selected-label")
                yield Button(
                    "Set as project folder",
                    id="project-open-btn",
                    variant="primary",
                )
        yield HintsBar(
            (
                [
                    ("Enter", "Select"),
                    ("Ctrl+U", "Parent dir", "screen.go_up"),
                    ("Ctrl+D", "Confirm", "screen.confirm"),
                    ("Esc", "Back", "screen.back"),
                ]
                if self._picker_mode
                else self._project_hints()
            )
        )

    def _project_hints(self) -> list[tuple[str, ...]]:
        hints: list[tuple[str, ...]] = [
            ("F1", "Editor", "app.switch_screen('editor')"),
            ("F2", "Viewer", "app.switch_screen('viewer')"),
            ("F3", "Modules", "app.switch_screen('modules')"),
            ("F4", "System", "app.switch_screen('system_state')"),
            ("F5", "Consistency", "app.switch_screen('consistency')"),
            ("F6", "Files", "app.switch_screen('project_files')"),
        ]
        hints.extend(
            [
                ("Enter", "Open file"),
                ("Ctrl+E", "Set entry", "screen.set_entry_from_tree"),
                ("Ctrl+U", "Parent dir", "screen.go_up"),
                ("Esc", "Projects", "app.project_selector"),
            ]
        )
        return hints

    def on_mount(self) -> None:
        self.query_one("#project-tree", ProjectTree).focus()

    # ------------------------------------------------------------------
    # Navigation (same breadcrumb pattern as DocumentPicker)
    # ------------------------------------------------------------------

    def _build_breadcrumb(self) -> str:
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
        tree = self.query_one("#project-tree", ProjectTree)
        tree.path = str(path)
        tree.reload()
        self.query_one("#project-path", Static).update(self._build_breadcrumb())

    def action_go_up(self) -> None:
        parent = self._root.parent
        if parent != self._root:
            self.action_navigate_to(str(parent))

    # ------------------------------------------------------------------
    # File selection
    # ------------------------------------------------------------------

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        path = Path(event.path)

        if self._picker_mode:
            if self._picker_step == 1:
                # Step 1: ignore file clicks, user should pick a folder
                self.notify(
                    "Select a folder first, then confirm it",
                    severity="warning",
                )
            elif self._picker_step == 2:
                # Step 2: pick entry point file
                if path.suffix.lower() in (".pltg", ".pgmd"):
                    self._selected_entry = path
                    try:
                        self.query_one("#project-selected-label", Label).update(f"[bold]Entry:[/bold] {path.name}")
                    except Exception:
                        pass
                else:
                    self.notify(
                        "Entry point must be .pltg or .pgmd",
                        severity="warning",
                    )
        else:
            self.post_message(FileOpenRequested(path))

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        """In picker step 1, highlight a directory as project root candidate."""
        if not self._picker_mode or self._picker_step != 1:
            return
        path = Path(event.path)
        self._project_dir = path
        try:
            self.query_one("#project-selected-label", Label).update(f"[bold]Folder:[/bold] {path.name}/")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_confirm(self) -> None:
        """Step 1: confirm folder → re-root tree.  Step 2: confirm entry point."""
        if not self._picker_mode:
            return

        if self._picker_step == 1:
            # Confirm project folder
            folder = self._project_dir
            if not folder:
                self.notify("Select a folder first.", severity="warning")
                return

            # Re-root tree to the selected folder
            self._root = folder
            tree = self.query_one("#project-tree", ProjectTree)
            tree.path = str(folder)
            tree.reload()
            self.query_one("#project-path", Static).update(self._build_breadcrumb())

            # Advance to step 2
            self._picker_step = 2
            try:
                self.query_one("#project-files-hint", Label).update("Step 2: Select .pltg or .pgmd entry point")
                self.query_one("#project-open-btn", Button).label = "Open project"
                self.query_one("#project-selected-label", Label).update("")
            except Exception:
                pass

        elif self._picker_step == 2:
            # Confirm entry point
            if not self._selected_entry:
                self.notify("Select a .pltg or .pgmd file first.", severity="warning")
                return
            self.post_message(ProjectSelected(self._selected_entry, self._root))

    def action_back(self) -> None:
        """Esc: step 2 → back to step 1.  Step 1 or browser → dismiss."""
        if self._picker_mode and self._picker_step == 2:
            # Go back to step 1: reset to original cwd root
            self._picker_step = 1
            self._selected_entry = None
            self._project_dir = None
            self._root = Path.cwd()

            tree = self.query_one("#project-tree", ProjectTree)
            tree.path = str(self._root)
            tree.reload()
            self.query_one("#project-path", Static).update(self._build_breadcrumb())
            try:
                self.query_one("#project-files-hint", Label).update("Step 1: Select project folder")
                self.query_one("#project-open-btn", Button).label = "Set as project folder"
                self.query_one("#project-selected-label", Label).update("")
            except Exception:
                pass
            return

        self.dismiss()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "project-open-btn":
            self.action_confirm()

    def action_set_entry_from_tree(self) -> None:
        """Set the highlighted file as entry point (browser mode)."""
        if self._picker_mode:
            return
        tree = self.query_one("#project-tree", ProjectTree)
        node = tree.cursor_node
        if node is None:
            return
        data = node.data
        if data is None:
            return
        path = data.path
        if path.suffix.lower() not in (".pltg", ".pgmd"):
            self.notify("Entry point must be .pltg or .pgmd", severity="warning")
            return

        from .editor import EntryPointChanged

        self.post_message(EntryPointChanged(path))
        self.notify(f"Entry point: {path.name}")
