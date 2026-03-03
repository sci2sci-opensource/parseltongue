"""Parseltongue TUI — Textual application shell.

Supports three modes:
- **Pipeline mode**: constructed with a RunConfig, goes straight to loading screen.
- **Standalone mode**: constructed via ``.standalone()``, starts with document picker.
- **History mode**: constructed via ``.from_history()``, views a cached run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App
from textual.binding import Binding

CSS_PATH = Path(__file__).parent / "app.tcss"


class ParseltongueApp(App):
    """Main Textual application for Parseltongue."""

    TITLE = "Parseltongue"
    CSS_PATH = CSS_PATH
    BINDINGS = [
        Binding("f1", "switch_screen('answer')", "Answer", show=True),
        Binding("f2", "switch_screen('passes')", "Passes", show=True),
        Binding("f3", "switch_screen('system_state')", "System", show=True),
        Binding("f4", "switch_screen('consistency')", "Consistency", show=True),
        Binding("f5", "show_history", "History", show=True),
        Binding("f6", "main_menu", "Menu", show=True),
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

    def on_configure_requested(self, event) -> None:
        """Main menu → Configure → suspend TUI, run terminal wizard."""
        from ..config import run_wizard

        with self.suspend():
            config = run_wizard()
        self._standalone_config = config

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

                self.push_screen(ConsistencyAlert(cached_text, fresh_text), callback=on_alert)
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
        if self._result is None and self._history_data is None:
            return
        if screen_name not in self._installed_screens:
            self.notify(f"Screen '{screen_name}' not available in this mode.", severity="warning")
            return
        # Pop current result screen, keep history browser in stack if present
        if self.screen.__class__.__name__ in (
            "AnswerScreen",
            "PassesScreen",
            "SystemStateScreen",
            "ConsistencyScreen",
        ):
            self.pop_screen()
        self.push_screen(screen_name)

    def action_show_history(self) -> None:
        from .screens.history_browser import HistoryBrowser

        self.push_screen(HistoryBrowser())

    def action_main_menu(self) -> None:
        if self._mode != "standalone":
            return
        from .screens.main_menu import MainMenu

        # Uninstall result screens to allow fresh install on next run
        for name in ("answer", "passes", "system_state", "consistency"):
            if name in self._installed_screens:
                self.uninstall_screen(name)
        self._result = None
        self._history_data = None

        while len(self.screen_stack) > 1:
            self.pop_screen()
        self.push_screen(MainMenu())

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
