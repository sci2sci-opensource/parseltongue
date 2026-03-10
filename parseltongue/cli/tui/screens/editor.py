"""Editor screen — tabbed file editors with provenance panel.

Replaces AnswerScreen layout for project mode: TextArea on the left
(with tabs for open files), provenance/state tree on the right.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Label, Static, TabbedContent, TabPane, TextArea

from ..pltg_highlight import EXTENSION_LEXERS, PygmentsTextArea
from ..widgets import FocusedTree
from ..widgets.hints_bar import HintsBar
from ..widgets.resizable_split import ResizableSplitMixin
from ..widgets.tree_builders import populate_system_tree


class EntryPointChanged(Message):
    """Broadcast when entry point changes."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path


class ProjectRunRequested(Message):
    """Broadcast to trigger a project run."""

    def __init__(self, entry_point: Path) -> None:
        super().__init__()
        self.entry_point = entry_point


class EditorScreen(ResizableSplitMixin, Screen):
    """Project editor — tabbed file editors with system state panel."""

    _split_grid_id = "editor-layout"

    BINDINGS = [
        ("f1", "app.switch_screen('editor')", "Editor"),
        ("f2", "app.switch_screen('viewer')", "Viewer"),
        ("f3", "app.switch_screen('modules')", "Modules"),
        ("f4", "app.switch_screen('system_state')", "System"),
        ("f5", "app.switch_screen('consistency')", "Consistency"),
        ("f6", "app.switch_screen('project_files')", "Files"),
        ("f7", "app.main_menu", "Menu"),
        ("escape", "app.project_selector", "Projects"),
        ("ctrl+s", "save_file", "Save"),
        ("ctrl+r", "run_project", "Run"),
        ("ctrl+e", "set_entry", "Set entry"),
        ("ctrl+w", "close_tab", "Close tab"),
        ("ctrl+d", "duplicate_tab", "Duplicate tab"),
        ("f9", "grow_right", "F9 Grow right"),
        ("f10", "grow_left", "F10 Grow left"),
    ]

    def __init__(self, project_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._project_dir = project_dir
        self._entry_point: Path | None = None
        self._open_files: dict[str, Path] = {}  # tab_id → file path
        self._modified: dict[str, bool] = {}  # tab_id → dirty flag
        self._tab_counter = 0
        self._system = None
        self._pending_open: list[Path] = []  # deferred until mount

    def compose(self) -> ComposeResult:
        with Horizontal(id="editor-layout"):
            with Container(id="editor-panel"):
                with Horizontal(id="editor-header"):
                    yield Label("Entry: (none)", id="entry-label")
                    yield Static("[@click=screen.save_file]Save[/]", id="editor-save-btn")
                yield TabbedContent(id="editor-tabs")
            with Container(id="editor-state-panel"):
                yield Label("System State", id="editor-state-title")
                yield FocusedTree("State", id="editor-state-tree")
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
                ("Ctrl+S", "Save", "screen.save_file"),
                ("Ctrl+R", "Run", "screen.run_project"),
                ("Ctrl+E", "Set entry", "screen.set_entry"),
                ("Ctrl+W", "Close", "screen.close_tab"),
                ("Ctrl+D", "Dup", "screen.duplicate_tab"),
                ("F9/F10", "Resize"),
                ("Esc", "Projects", "app.project_selector"),
            ]
        )
        yield HintsBar(hints)

    def on_mount(self) -> None:
        if self._entry_point:
            self.query_one("#entry-label", Label).update(f"Entry: {self._entry_point.name}")
        if self._pending_open:
            paths = list(self._pending_open)
            self._pending_open.clear()
            for path in paths:
                self.call_after_refresh(self.open_file, path)
            # Focus entry point tab after all files open
            if self._entry_point:
                self.call_after_refresh(self._focus_entry_tab)

    # ------------------------------------------------------------------
    # File management
    # ------------------------------------------------------------------

    def open_file(self, path: Path) -> None:
        """Open a file in a new tab, or switch to it if already open."""
        # Defer if not yet mounted
        if not self.is_mounted:
            self._pending_open.append(path)
            return

        abs_path = path.resolve()

        # Check if already open
        for tab_id, existing in self._open_files.items():
            if existing == abs_path:
                tabs = self.query_one("#editor-tabs", TabbedContent)
                tabs.active = tab_id
                return

        # Read file
        try:
            content = abs_path.read_text()
        except Exception as exc:
            self.notify(f"Cannot read {path.name}: {exc}", severity="error")
            return

        # Create tab
        self._tab_counter += 1
        tab_id = f"file-{self._tab_counter}"
        self._open_files[tab_id] = abs_path
        self._modified[tab_id] = False

        # Determine Pygments lexer from file extension
        suffix = abs_path.suffix.lower()
        lexer_name = EXTENSION_LEXERS.get(suffix, "text")
        editor = PygmentsTextArea(content, pygments_lexer=lexer_name, id=f"ta-{tab_id}")

        # Determine tab label
        label = path.name
        if self._entry_point and abs_path == self._entry_point.resolve():
            label = f"★ {label}"

        tabs = self.query_one("#editor-tabs", TabbedContent)
        pane = TabPane(label, editor, id=tab_id)
        tabs.add_pane(pane)
        tabs.active = tab_id

    def _focus_entry_tab(self) -> None:
        """Switch to the entry point's tab."""
        if not self._entry_point:
            return
        entry_resolved = self._entry_point.resolve()
        for tab_id, path in self._open_files.items():
            if path == entry_resolved:
                self.query_one("#editor-tabs", TabbedContent).active = tab_id
                return

    def _active_tab_id(self) -> str | None:
        """Return the active tab's pane id."""
        tabs = self.query_one("#editor-tabs", TabbedContent)
        return tabs.active if tabs.active else None

    def _active_editor(self) -> TextArea | None:
        """Return the TextArea in the active tab."""
        tab_id = self._active_tab_id()
        if not tab_id:
            return None
        try:
            pane = self.query_one(f"#{tab_id}", TabPane)
            return pane.query_one(TextArea)
        except Exception:
            return None

    def reload_from_disk(self) -> None:
        """Reload all non-dirty open files from disk, preserving cursor position."""
        reloaded = []
        for tab_id, path in self._open_files.items():
            if self._modified.get(tab_id):
                continue
            try:
                content = path.read_text()
            except Exception:
                continue
            try:
                pane = self.query_one(f"#{tab_id}", TabPane)
                ta = pane.query_one(TextArea)
                if ta.text != content:
                    cursor = ta.cursor_location
                    scroll_y = ta.scroll_offset.y
                    ta.load_text(content)
                    # Clamp cursor to new content bounds
                    lines = content.split("\n")
                    row = min(cursor[0], len(lines) - 1)
                    col = min(cursor[1], len(lines[row]) if lines else 0)
                    ta.cursor_location = (row, col)
                    ta.scroll_to(0, scroll_y, animate=False)
                    reloaded.append(path.name)
            except Exception:
                pass
        if reloaded:
            self.notify(f"Reloaded: {', '.join(reloaded)}")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_save_file(self) -> None:
        """Save the active tab's file."""
        tab_id = self._active_tab_id()
        if not tab_id or tab_id not in self._open_files:
            return

        editor = self._active_editor()
        if not editor:
            return

        path = self._open_files[tab_id]
        try:
            path.write_text(editor.text)
            self._modified[tab_id] = False
            self.notify(f"Saved {path.name}")
        except Exception as exc:
            self.notify(f"Save failed: {exc}", severity="error")

    def action_set_entry(self) -> None:
        """Set the active tab's file as the entry point."""
        tab_id = self._active_tab_id()
        if not tab_id or tab_id not in self._open_files:
            return

        path = self._open_files[tab_id]
        if path.suffix.lower() not in (".pltg", ".pgmd"):
            self.notify("Entry point must be .pltg or .pgmd", severity="warning")
            return

        self._entry_point = path
        self.query_one("#entry-label", Label).update(f"Entry: {path.name}")

        # Update tab labels to show/hide star
        self._refresh_tab_labels()

        self.post_message(EntryPointChanged(path))
        self.notify(f"Entry point: {path.name}")

    def action_run_project(self) -> None:
        """Run the project from the entry point."""
        if not self._entry_point:
            self.notify("No entry point set. Use Ctrl+E.", severity="warning")
            return

        # Save modified files first
        for tab_id, modified in self._modified.items():
            if modified and tab_id in self._open_files:
                path = self._open_files[tab_id]
                try:
                    pane = self.query_one(f"#{tab_id}", TabPane)
                    editor = pane.query_one(TextArea)
                    path.write_text(editor.text)
                    self._modified[tab_id] = False
                except Exception:
                    pass

        self.post_message(ProjectRunRequested(self._entry_point))

    def action_close_tab(self) -> None:
        """Close the active tab."""
        tab_id = self._active_tab_id()
        if not tab_id or tab_id not in self._open_files:
            return
        tabs = self.query_one("#editor-tabs", TabbedContent)
        tabs.remove_pane(tab_id)
        self._open_files.pop(tab_id, None)
        self._modified.pop(tab_id, None)

    def action_duplicate_tab(self) -> None:
        """Open a duplicate of the active tab (bypasses already-open check)."""
        tab_id = self._active_tab_id()
        if not tab_id or tab_id not in self._open_files:
            return
        path = self._open_files[tab_id]
        try:
            content = path.read_text()
        except Exception as exc:
            self.notify(f"Cannot read {path.name}: {exc}", severity="error")
            return
        self._tab_counter += 1
        new_id = f"file-{self._tab_counter}"
        self._open_files[new_id] = path
        self._modified[new_id] = False
        suffix = path.suffix.lower()
        lexer_name = EXTENSION_LEXERS.get(suffix, "text")
        editor = PygmentsTextArea(content, pygments_lexer=lexer_name, id=f"ta-{new_id}")
        label = f"{path.name} (dup)"
        tabs = self.query_one("#editor-tabs", TabbedContent)
        pane = TabPane(label, editor, id=new_id)
        tabs.add_pane(pane)
        tabs.active = new_id

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Track modifications."""
        tab_id = self._active_tab_id()
        if tab_id:
            self._modified[tab_id] = True

    # ------------------------------------------------------------------
    # State tree
    # ------------------------------------------------------------------

    def update_system(self, system) -> None:
        """Update the state tree and editor highlights after a run."""
        self._system = system
        if not self.is_mounted:
            return
        tree = self.query_one("#editor-state-tree", FocusedTree)
        tree.clear()
        tree.root.expand()
        if system is not None:
            populate_system_tree(tree.root, system)

        # Push system to all open PygmentsTextAreas for error/unreachable highlighting
        for editor in self.query(PygmentsTextArea):
            editor.set_system(system)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_tab_labels(self) -> None:
        """Update tab labels to reflect entry point marker."""
        tabs = self.query_one("#editor-tabs", TabbedContent)
        entry_resolved = self._entry_point.resolve() if self._entry_point else None

        for tab_id, path in self._open_files.items():
            try:
                self.query_one(f"#{tab_id}", TabPane)  # verify pane exists
                name = path.name
                if entry_resolved and path.resolve() == entry_resolved:
                    name = f"★ {name}"
                # TabPane doesn't have a direct label setter, so we update via
                # the internal tab widget
                tab_widget = tabs.get_tab(tab_id)
                tab_widget.label = name  # type: ignore[assignment]
            except Exception:
                pass
