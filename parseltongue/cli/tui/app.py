"""Parseltongue TUI — Textual application shell.

Supports three modes:
- **Pipeline mode**: constructed with a RunConfig, goes straight to loading screen.
- **Standalone mode**: constructed via ``.standalone()``, starts with document picker.
- **History mode**: constructed via ``.from_history()``, views a cached run.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from textual.app import App
from textual.binding import Binding
from textual.widgets import Label, TabPane, TextArea

log = logging.getLogger("parseltongue.cli")

CSS_PATH = Path(__file__).parent / "app.tcss"


class ParseltongueApp(App):
    """Main Textual application for Parseltongue."""

    TITLE = "Parseltongue"
    CSS_PATH = CSS_PATH
    BINDINGS = [
        Binding("f7", "main_menu", "Menu", show=False),
        Binding("ctrl+q", "request_quit", "Quit", show=False),
    ]

    def __init__(
        self,
        config=None,
        *,
        standalone_config: dict[str, Any] | None = None,
        history_data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._run_config = config  # RunConfig for pipeline mode
        self._standalone_config = standalone_config  # dict from config.toml
        self._history_data = history_data  # dict from history DB
        self._result = None
        self._selected_paths: list[Path] = []

    @property
    def _mode(self) -> str:
        if self._history_data is not None:
            return "history"
        if self._standalone_config is not None:
            return "standalone"
        return "pipeline"

    @classmethod
    def standalone(cls, cli_config: dict[str, Any]) -> ParseltongueApp:
        """Create app in standalone mode (starts with doc picker)."""
        return cls(standalone_config=cli_config)

    @classmethod
    def from_history(cls, run_data: dict[str, Any]) -> ParseltongueApp:
        """Create app to view a cached historical run."""
        return cls(history_data=run_data)

    # ------------------------------------------------------------------
    # Compose / mount
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        if self._mode == "standalone":
            from .screens.main_menu import MainMenu

            self.push_screen(MainMenu())
        elif self._mode == "history":
            self._install_history_screens(then_go_to_answer=True)
        else:
            self._start_interactive_pipeline()

    # ------------------------------------------------------------------
    # Main menu handlers
    # ------------------------------------------------------------------

    def on_new_run_requested(self, event) -> None:
        """Main menu → New Run → show document picker."""
        from .screens.document_picker import DocumentPicker

        self.push_screen(DocumentPicker(selected=self._selected_paths))

    def on_history_requested(self, event) -> None:
        """Main menu → History → show history browser."""
        from .screens.history_browser import HistoryBrowser

        self.push_screen(HistoryBrowser())

    def on_project_requested(self, event) -> None:
        """Main menu → Load Project → show project file picker."""
        from .screens.project_files import ProjectFilesScreen

        self.push_screen(ProjectFilesScreen(picker_mode=True))

    def on_recent_projects_requested(self, event) -> None:
        """Main menu → Recent projects → show saved projects list."""
        from .screens.recent_projects import RecentProjects

        self.push_screen(RecentProjects())

    def on_export_run_requested(self, event) -> None:
        """History → Export run as project → show folder picker."""
        from .screens.folder_picker import FolderPicker

        self._export_run_id = event.run_id
        self.push_screen(FolderPicker())

    def on_folder_selected(self, event) -> None:
        """Folder picker confirmed → export run to that folder."""
        run_id = getattr(self, "_export_run_id", None)
        if run_id is None:
            return
        from ..history import export_run_as_project

        target = event.folder
        try:
            entry = export_run_as_project(run_id, target)
            self.notify(f"Exported to {target}")
            self._export_run_id = None
            self._start_project_mode(target, entry_point=entry)
        except Exception as exc:
            self.notify(f"Export failed: {exc}", severity="error")

    def on_project_selected(self, event) -> None:
        """Project picker → entry point selected → start project mode."""
        self._start_project_mode(event.project_dir, entry_point=event.entry_point)

    def on_project_open_requested(self, event) -> None:
        """Recent projects → re-open a saved project."""
        self._project_id = event.project_id
        self._start_project_mode(
            event.project_dir,
            entry_point=event.entry_point,
            open_files=event.open_files,
        )

    def _start_project_mode(
        self,
        project_dir,
        entry_point=None,
        open_files: list[Path] | None = None,
    ) -> None:
        """Install project screens and push the editor."""
        from .screens.editor import EditorScreen
        from .screens.modules import ModulesScreen
        from .screens.project_files import ProjectFilesScreen
        from .screens.viewer import ViewerScreen

        # Uninstall previous screens if any
        for name in (
            "editor",
            "modules",
            "project_files",
            "viewer",
            "system_state",
            "consistency",
            "answer",
            "passes",
        ):
            if name in self._installed_screens:
                self.uninstall_screen(name)

        self._project_dir = project_dir
        self._editor_screen = EditorScreen(project_dir)
        self._modules_screen = ModulesScreen()
        self._project_files_screen = ProjectFilesScreen(project_dir)
        self._viewer_screen = None

        # Install viewer only if the project has .pgmd files
        has_pgmd = any(project_dir.rglob("*.pgmd"))
        if has_pgmd:
            self._viewer_screen = ViewerScreen()

        # Install all project screens — subclassed system/consistency with project bindings
        empty_result = _ProjectResult(None)
        self.install_screen(self._editor_screen, name="editor")
        self.install_screen(self._modules_screen, name="modules")
        self.install_screen(self._project_files_screen, name="project_files")
        if self._viewer_screen is not None:
            self.install_screen(self._viewer_screen, name="viewer")
        self.install_screen(_make_project_system_state(empty_result), name="system_state")
        self.install_screen(_make_project_consistency(empty_result), name="consistency")

        # Set entry point and open it in editor
        if entry_point is not None:
            self._editor_screen._entry_point = entry_point
            self._editor_screen.open_file(entry_point)

        # Open additional files from saved project state
        if open_files:
            for f in open_files:
                if f.is_file() and (entry_point is None or f.resolve() != entry_point.resolve()):
                    self._editor_screen.open_file(f)

        # Save to project history
        if entry_point is not None:
            from ..history import save_project

            pid = getattr(self, "_project_id", None)
            self._project_id = save_project(
                str(project_dir),
                str(entry_point),
                [str(f) for f in (open_files or [])],
                project_id=pid,
            )

        # Clean up the stack: pop back to base, keep MainMenu, push editor
        while len(self.screen_stack) > 1:
            top = self.screen.__class__.__name__
            if top == "MainMenu":
                break
            self.pop_screen()
        self.push_screen("editor")

        # Start file watcher
        self._start_file_watcher()

        # Auto-run the project to load the system
        if entry_point is not None:
            self.run_worker(self._run_project(entry_point), exclusive=True)

    def on_file_open_requested(self, event) -> None:
        """ProjectFilesScreen → open file in editor."""
        if hasattr(self, "_editor_screen"):
            self._editor_screen.open_file(event.path)
            # Switch to editor screen
            if self.screen.__class__.__name__ != "EditorScreen":
                if self.screen.__class__.__name__ in (
                    "ProjectFilesScreen",
                    "ModulesScreen",
                    "SystemStateScreen",
                    "ConsistencyScreen",
                ):
                    self.pop_screen()
                self.push_screen("editor")

    def on_project_run_requested(self, event) -> None:
        """EditorScreen → Ctrl+R → run the project."""

        self.run_worker(self._run_project(event.entry_point), exclusive=True)

    async def _run_project(self, entry_point) -> None:
        """Run a .pltg/.pgmd project in a background thread."""
        import asyncio

        from parseltongue.core.loader import LazyLoader

        entry_path = str(entry_point)

        def do_run():
            from parseltongue.core.notebooks.companion import CompanionTracker, companion_path_for
            from parseltongue.core.notebooks.companion_integrity import check_corruption
            from parseltongue.core.notebooks.pgmd import parse_pgmd

            loader = LazyLoader()
            if entry_path.endswith(".pgmd"):
                source = entry_point.read_text()
                companion = companion_path_for(entry_point)
                companion_text = companion.read_text() if companion.exists() else ""

                # If no companion or corrupted, write all blocks with proper markers
                if not companion_text.strip() or check_corruption(companion_text):
                    tracker = CompanionTracker(entry_point, companion)
                    pltg_blocks = [b for b in parse_pgmd(source) if b.kind == "pltg"]
                    for bn, block in enumerate(pltg_blocks):
                        tracker.execute(bn, block.content)

                load_path = str(companion)
            else:
                load_path = entry_path
            loader.load_main(load_path)
            return loader

        try:
            loader = await asyncio.to_thread(do_run)
        except Exception as exc:
            log.error("Project run failed: %s", exc, exc_info=True)
            self.notify(f"Run failed: {exc}", severity="error")
            return

        result = loader.last_result
        system = result.system

        if not result.ok:
            log.error("Project run partial:\n%s", result.summary())
            self.notify(f"Run errors: {len(result.errors)} failed, {len(result.skipped)} skipped", severity="warning")

        # Update screens
        if hasattr(self, "_editor_screen"):
            self._editor_screen.update_system(system)

        if hasattr(self, "_modules_screen"):
            self._modules_screen.update(system, loader)

        if getattr(self, "_viewer_screen", None) is not None:
            from parseltongue.core.notebooks.companion import companion_path_for

            pgmd_files: dict[str, tuple[Path, Path, str]] = {}
            project_dir = getattr(self, "_project_dir", None)
            entry_stem = (
                self._editor_screen._entry_point.stem
                if hasattr(self, "_editor_screen") and self._editor_screen._entry_point
                else None
            )
            if project_dir:
                paths = sorted(project_dir.rglob("*.pgmd"))
                # Entry point's pgmd first
                if entry_stem:
                    paths.sort(key=lambda p: p.stem != entry_stem)
                for p in paths:
                    try:
                        pgmd_files[p.stem] = (p, companion_path_for(p), p.read_text())
                    except Exception:
                        pass
            self._viewer_screen.update(pgmd_files)  # type: ignore[union-attr]

        # Reinstall system/consistency with new data (project subclasses)
        project_result = _ProjectResult(system, loader)

        # Pop active screen if it's one we're about to reinstall
        reopen_screen = None
        for name in ("system_state", "consistency"):
            if name in self._installed_screens:
                if self.screen is self._installed_screens[name]:
                    reopen_screen = name
                    self.pop_screen()
                self.uninstall_screen(name)

        self.install_screen(_make_project_system_state(project_result), name="system_state")
        self.install_screen(_make_project_consistency(project_result), name="consistency")

        # Re-open the screen if the user was viewing it
        if reopen_screen:
            self.push_screen(reopen_screen)

        # Refresh file snapshot so watcher doesn't re-notify about run outputs
        self._file_snapshot = self._snapshot_project()

        self.notify("Project run complete.")

    def on_entry_point_changed(self, event) -> None:
        """Update entry point across project screens and persist to DB."""
        if hasattr(self, "_editor_screen"):
            self._editor_screen._entry_point = event.path
            self._editor_screen.query_one("#entry-label", Label).update(f"Entry: {event.path.name}")
            self._save_project_state()

    def on_configure_requested(self, event) -> None:
        """Main menu → Configure → open settings screen."""
        from .screens.configure import ConfigureScreen

        self.push_screen(ConfigureScreen())

    def on_quit_requested(self, event) -> None:
        """Main menu → Quit → show quit confirmation."""
        self.action_request_quit()

    # ------------------------------------------------------------------
    # Standalone mode: doc picker → query input → pipeline
    # ------------------------------------------------------------------

    def on_documents_selected(self, event) -> None:
        """Handle document selection — docs already ingested by picker."""
        from .screens.query_input import QueryInput

        self._selected_paths = list(event.paths)
        self._ingested_docs = event.ingested
        self.push_screen(
            QueryInput(
                doc_count=len(event.paths),
                ingested=event.ingested,
                doc_paths=self._selected_paths,
            )
        )

    def on_query_submitted(self, event) -> None:
        """Handle query submission → build RunConfig, run pipeline."""
        from ..runner import RunConfig

        cfg = self._standalone_config or {}
        prov = cfg.get("provider", {})
        reasoning_cfg = cfg.get("reasoning", {})

        reason_val: bool | int | None = None
        if reasoning_cfg.get("enabled"):
            reason_val = reasoning_cfg.get("tokens") or True

        self._run_config = RunConfig(
            documents=[(p.stem, str(p)) for p in self._selected_paths],
            query=event.query,
            model=prov.get("model", "anthropic/claude-sonnet-4.6"),
            reasoning=reason_val,
            provider_config=prov,
        )

        self._start_interactive_pipeline()

    # ------------------------------------------------------------------
    # Interactive pipeline execution (TUI mode)
    # ------------------------------------------------------------------

    def _start_interactive_pipeline(self) -> None:
        from ..runner import create_interactive_pipeline
        from .screens.live_pass import LivePassScreen

        pre = getattr(self, "_ingested_docs", None) or None
        self._pipeline, self._history_run_id = create_interactive_pipeline(self._run_config, pre_ingested=pre)
        for name, err in self._run_config.ingest_errors.items():
            self.notify(f"{name}: {err}", severity="error", timeout=10)
        self.push_screen(LivePassScreen(self._pipeline))

    def on_passes_complete(self, event) -> None:
        """All 4 passes done — finalize and show results."""
        from .. import history

        result = self._pipeline.finalize()
        self._result = result

        if hasattr(self, "_history_run_id"):
            try:
                history.complete_run(self._history_run_id, result)
            except Exception:
                pass

        self._install_result_screens()
        self._go_to_answer()

    # ------------------------------------------------------------------
    # Screen installation
    # ------------------------------------------------------------------

    def _install_result_screens(self) -> None:
        """Install screens from a live PipelineResult."""
        from .screens.answer import AnswerScreen
        from .screens.consistency import ConsistencyScreen
        from .screens.passes import PassesScreen
        from .screens.system_state import SystemStateScreen

        for name in ("answer", "passes", "system_state", "consistency"):
            if name in self._installed_screens:
                self.uninstall_screen(name)

        result = self._result
        self.install_screen(AnswerScreen(result), name="answer")  # type: ignore[arg-type]
        self.install_screen(PassesScreen(result), name="passes")  # type: ignore[arg-type]
        self.install_screen(SystemStateScreen(result), name="system_state")  # type: ignore[arg-type]
        self.install_screen(ConsistencyScreen(result), name="consistency")  # type: ignore[arg-type]

    def _install_history_screens(self, then_go_to_answer: bool = False) -> None:
        """Install screens from cached history data (no live System)."""
        data = self._history_data
        assert data is not None

        hist = _HistoryResult(data)

        # Recompute consistency and compare with cached
        cached_raw = data.get("consistency", "")
        if hist.system is not None and cached_raw:
            import json

            from parseltongue.core.engine import ConsistencyReport

            fresh_report = hist.system.consistency()
            fresh_text = str(fresh_report)

            # Parse cached — could be JSON (new) or plain text (legacy)
            cached_dict = None
            try:
                cached_dict = json.loads(cached_raw) if isinstance(cached_raw, str) else cached_raw
                cached_report = ConsistencyReport.from_dict(cached_dict)
                cached_text = str(cached_report)
            except (json.JSONDecodeError, KeyError, TypeError):
                cached_text = str(cached_raw)

            # Compare structured data if available, otherwise strings
            changed = fresh_report.to_dict() != cached_dict if cached_dict is not None else fresh_text != cached_text
            if changed:
                from .screens.consistency_alert import ConsistencyAlert

                def on_alert(use_current: bool) -> None:
                    if use_current and hist.output is not None:
                        hist.output.consistency = fresh_report.to_dict()
                    self._finish_install_history(hist, then_go_to_answer)

                self.push_screen(ConsistencyAlert(cached_text, fresh_text), callback=on_alert)  # type: ignore[arg-type]
                return

        self._finish_install_history(hist, then_go_to_answer)

    def _finish_install_history(self, hist: "_HistoryResult", go_to_answer: bool = False) -> None:
        from .screens.answer import AnswerScreen
        from .screens.consistency import ConsistencyScreen
        from .screens.passes import PassesScreen
        from .screens.system_state import SystemStateScreen

        self.install_screen(AnswerScreen(hist), name="answer")  # type: ignore[arg-type]
        self.install_screen(PassesScreen(hist), name="passes")  # type: ignore[arg-type]
        self.install_screen(SystemStateScreen(hist), name="system_state")  # type: ignore[arg-type]
        self.install_screen(ConsistencyScreen(hist), name="consistency")  # type: ignore[arg-type]
        if go_to_answer:
            self.push_screen("answer")

    def _go_to_answer(self) -> None:
        from .screens.main_menu import MainMenu

        # Clear run screens but keep the base
        while len(self.screen_stack) > 1:
            self.pop_screen()
        if self._mode == "standalone":
            self.push_screen(MainMenu())
        self.push_screen("answer")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def action_switch_screen(self, screen_name: str) -> None:
        if screen_name not in self._installed_screens:
            return
        switchable = (
            "AnswerScreen",
            "PassesScreen",
            "SystemStateScreen",
            "ConsistencyScreen",
            "EditorScreen",
            "ModulesScreen",
            "ProjectFilesScreen",
            "ViewerScreen",
            "ProjectSystemStateScreen",
            "ProjectConsistencyScreen",
        )
        if self.screen.__class__.__name__ in switchable:
            self.pop_screen()
        self.push_screen(screen_name)

    def action_show_history(self) -> None:
        from .screens.history_browser import HistoryBrowser

        self.push_screen(HistoryBrowser())

    def action_request_quit(self) -> None:
        """Show quit confirmation modal."""
        from .screens.quit_modal import QuitModal

        def on_quit(confirmed: bool | None) -> None:
            if confirmed:
                self.exit()

        self.push_screen(QuitModal(), callback=on_quit)

    def action_main_menu(self) -> None:
        if self._mode != "standalone":
            return
        from .screens.main_menu import MainMenu

        # Stop file watcher and save project state before leaving
        self._stop_file_watcher()
        self._save_project_state()

        # Pop all screens off the stack first
        while len(self.screen_stack) > 1:
            self.pop_screen()

        # Now safe to uninstall (nothing in stack)
        for name in (
            "answer",
            "passes",
            "system_state",
            "consistency",
            "editor",
            "modules",
            "project_files",
            "viewer",
        ):
            if name in self._installed_screens:
                self.uninstall_screen(name)
        self._result = None
        self._history_data = None
        if hasattr(self, "_project_dir"):
            del self._project_dir

        self.push_screen(MainMenu())

    def action_project_selector(self) -> None:
        """Return to the Recent Projects screen from project mode."""
        from .screens.recent_projects import RecentProjects

        # Stop file watcher and save project state before leaving
        self._stop_file_watcher()
        self._save_project_state()

        # Pop all screens off the stack first
        while len(self.screen_stack) > 1:
            self.pop_screen()

        # Uninstall project screens
        for name in (
            "answer",
            "passes",
            "system_state",
            "consistency",
            "editor",
            "modules",
            "project_files",
            "viewer",
        ):
            if name in self._installed_screens:
                self.uninstall_screen(name)
        self._result = None
        self._history_data = None
        if hasattr(self, "_project_dir"):
            del self._project_dir

        self.push_screen(RecentProjects())

    def _save_project_state(self) -> None:
        """Persist current project's open files to the database."""
        if not hasattr(self, "_project_dir") or not hasattr(self, "_editor_screen"):
            return
        editor = self._editor_screen
        if not editor._entry_point:
            return

        from ..history import save_project

        open_files = [str(p) for p in editor._open_files.values()]
        pid = getattr(self, "_project_id", None)
        self._project_id = save_project(
            str(self._project_dir),
            str(editor._entry_point),
            open_files,
            project_id=pid,
        )

    # ------------------------------------------------------------------
    # File watcher
    # ------------------------------------------------------------------

    _WATCH_EXTENSIONS = {".pltg", ".pgmd"}
    _WATCH_INTERVAL = 2.0  # seconds

    def _snapshot_project(self) -> dict[str, str]:
        """Return {relative_path: content_hash} for all project files."""
        project_dir = getattr(self, "_project_dir", None)
        if not project_dir:
            return {}
        snapshot: dict[str, str] = {}
        for ext in self._WATCH_EXTENSIONS:
            for p in project_dir.rglob(f"*{ext}"):
                if p.name.startswith("."):
                    continue
                try:
                    h = hashlib.md5(p.read_bytes()).hexdigest()
                    snapshot[str(p.relative_to(project_dir))] = h
                except Exception:
                    pass
        return snapshot

    def _start_file_watcher(self) -> None:
        """Begin periodic file watching for the current project."""
        # Stop any existing watcher
        old = getattr(self, "_watch_timer", None)
        if old is not None:
            old.stop()
        self._file_snapshot = self._snapshot_project()
        self._watch_timer = self.set_interval(self._WATCH_INTERVAL, self._check_file_changes)

    def _stop_file_watcher(self) -> None:
        old = getattr(self, "_watch_timer", None)
        if old is not None:
            old.stop()
            self._watch_timer = None  # type: ignore[assignment]

    def _check_file_changes(self) -> None:
        """Compare current files against snapshot, prompt to reload on changes."""
        # Check companion integrity separately (dot-files excluded from general snapshot)
        viewer = getattr(self, "_viewer_screen", None)
        if viewer and viewer._tabs:
            viewer.check_companion_integrity()
        elif viewer:
            log.debug("Watcher: viewer exists but _tabs empty (%d tabs)", len(viewer._tabs))

        current = self._snapshot_project()
        old = getattr(self, "_file_snapshot", {})
        if current == old:
            return

        added = set(current) - set(old)
        removed = set(old) - set(current)
        modified = {k for k in set(current) & set(old) if current[k] != old[k]}

        # Filter out files the editor just saved (dirty flag was just cleared)
        # Only suppress if the editor content matches disk (i.e. we saved it)
        editor = getattr(self, "_editor_screen", None)
        if editor and editor.is_mounted:
            project_dir = self._project_dir
            for tid, tp in editor._open_files.items():
                try:
                    rel = str(tp.relative_to(project_dir))
                except ValueError:
                    continue
                if rel not in modified:
                    continue
                # If the editor has this file open and its content matches
                # the new disk content, we saved it — suppress notification
                try:
                    pane = editor.query_one(f"#{tid}", TabPane)
                    ta = pane.query_one(TextArea)
                    disk_content = tp.read_text()
                    if ta.text == disk_content:
                        modified.discard(rel)
                except Exception:
                    pass

        if not added and not removed and not modified:
            self._file_snapshot = current
            return

        # Pause watcher while dialog is open
        self._watch_timer.pause()

        parts = []
        if added:
            parts.append(f"{len(added)} added")
        if removed:
            parts.append(f"{len(removed)} removed")
        if modified:
            names = ", ".join(Path(f).name for f in sorted(modified)[:3])
            if len(modified) > 3:
                names += f" +{len(modified) - 3}"
            parts.append(f"modified: {names}")

        msg = f"Files changed ({', '.join(parts)}). Reload project?"

        from .screens.confirm import ConfirmModal

        def on_confirm(confirmed: bool | None) -> None:
            self._file_snapshot = self._snapshot_project()
            if confirmed:
                self._reload_project()
            self._watch_timer.resume()

        self.push_screen(ConfirmModal(msg), callback=on_confirm)

    def _reload_project(self) -> None:
        """Reload open editor files from disk and re-run the project."""
        editor = getattr(self, "_editor_screen", None)
        if editor:
            editor.reload_from_disk()

        entry = editor._entry_point if editor else None
        if entry:
            self.run_worker(self._run_project(entry), exclusive=True)

    def on_run_selected(self, event) -> None:
        """Handle history run selection — push answer on top of history browser."""
        from ..history import get_run

        data = get_run(event.run_id)
        if not data or data["status"] != "completed":
            self.notify("Run has no cached result.", severity="warning")
            return

        # Uninstall previous result screens if any
        for name in ("answer", "passes", "system_state", "consistency"):
            if name in self._installed_screens:
                self.uninstall_screen(name)

        self._history_data = data
        self._install_history_screens(then_go_to_answer=True)


_PROJECT_BINDINGS: list[Binding | tuple[str, str] | tuple[str, str, str]] = [
    ("f1", "app.switch_screen('editor')", "Editor"),
    ("f2", "app.switch_screen('viewer')", "Viewer"),
    ("f3", "app.switch_screen('modules')", "Modules"),
    ("f4", "app.switch_screen('system_state')", "System"),
    ("f5", "app.switch_screen('consistency')", "Consistency"),
    ("f6", "app.switch_screen('project_files')", "Files"),
    ("f7", "app.main_menu", "Menu"),
    ("escape", "app.project_selector", "Projects"),
]

_PROJECT_HINTS: list[tuple[str, ...]] = [
    ("F1", "Editor", "app.switch_screen('editor')"),
    ("F2", "Viewer", "app.switch_screen('viewer')"),
    ("F3", "Modules", "app.switch_screen('modules')"),
    ("F4", "System", "app.switch_screen('system_state')"),
    ("F5", "Consistency", "app.switch_screen('consistency')"),
    ("F6", "Files", "app.switch_screen('project_files')"),
    ("Esc", "Projects", "app.project_selector"),
]


def _make_project_system_state(result):
    from .screens.system_state import SystemStateScreen

    class ProjectSystemStateScreen(SystemStateScreen):
        BINDINGS = _PROJECT_BINDINGS
        HINTS = _PROJECT_HINTS

    return ProjectSystemStateScreen(result)


def _make_project_consistency(result):
    from .screens.consistency import ConsistencyScreen

    class ProjectConsistencyScreen(ConsistencyScreen):
        BINDINGS = _PROJECT_BINDINGS
        HINTS = _PROJECT_HINTS

    return ProjectConsistencyScreen(result)


class _ProjectResult:
    """Minimal adapter so project System can be used by SystemStateScreen / ConsistencyScreen."""

    def __init__(self, system, loader=None) -> None:
        self.system = system
        self.loader = loader
        self.pass_systems: dict[str, Any] = {}
        self.output = None


class _HistoryResult:
    """Minimal adapter so history data can be used by AnswerScreen / PassesScreen."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.pass1_source = data.get("pass1_source", "")
        self.pass2_source = data.get("pass2_source", "")
        self.pass3_source = data.get("pass3_source", "")
        self.pass4_raw = data.get("pass4_raw", "")
        self._system_state_json = data.get("system_state", "")
        self._documents = data.get("documents", "[]")
        self.output = _HistoryOutput(data)
        self.system, self.pass_systems = self._rebuild_system()

    def _rebuild_system(self):
        """Rebuild system and per-pass snapshots.

        Returns (final_system, {pass_num: system_after_that_pass}).
        """
        import copy
        import json

        from parseltongue.core import System, load_source

        # Register documents from serialized system state
        system = System()
        if self._system_state_json:
            try:
                for name, text in json.loads(self._system_state_json).get("documents", {}).items():
                    system.register_document(name, text)
            except Exception:
                pass

        # Replay incrementally: each pass builds on the previous
        pass_systems: dict[int, System] = {}
        for pass_num, source in [
            (1, self.pass1_source),
            (2, self.pass2_source),
            (3, self.pass3_source),
        ]:
            if source:
                try:
                    load_source(system, source)
                except Exception:
                    pass
            pass_systems[pass_num] = copy.deepcopy(system)

        # If we have serialized state, use it as the authoritative final
        # (preserves verification results that replay may not reproduce)
        if self._system_state_json:
            try:
                final = System.from_dict(json.loads(self._system_state_json))
                pass_systems[4] = final
                return final, pass_systems
            except Exception:
                pass

        pass_systems[4] = system
        return system, pass_systems


class _HistoryOutput:
    """Minimal adapter for ResolvedOutput from cached data."""

    def __init__(self, data: dict[str, Any]) -> None:
        import json

        self.markdown = data.get("output_md", "")

        # Consistency: JSON dict (new) or plain text (legacy)
        raw = data.get("consistency", "")
        try:
            from parseltongue.core.engine import ConsistencyReport

            d = json.loads(raw) if isinstance(raw, str) else raw
            self.consistency = str(ConsistencyReport.from_dict(d))
        except (json.JSONDecodeError, KeyError, TypeError):
            self.consistency = str(raw) if raw else ""

        refs_raw = data.get("refs", "[]")
        parsed = json.loads(refs_raw) if refs_raw else []
        self.references = [_HistoryRef(r) for r in parsed]

    def __str__(self) -> str:
        return self.markdown


class _HistoryRef:
    """Minimal adapter for Reference from cached data."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.type = data.get("type", "")
        self.name = data.get("name", "")
        self.value = data.get("value")
        self.provenance = None
        self.error = data.get("error")
