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
        Binding("q", "quit", "Quit", show=True),
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
            from .screens.document_picker import DocumentPicker

            self.push_screen(DocumentPicker())
        elif self._mode == "history":
            self._install_history_screens()
            self._go_to_answer()
        else:
            self._start_interactive_pipeline()

    # ------------------------------------------------------------------
    # Standalone mode: doc picker → query input → pipeline
    # ------------------------------------------------------------------

    def on_documents_selected(self, event) -> None:
        """Handle document selection → show query input."""
        from .screens.query_input import QueryInput

        self._selected_paths = list(event.paths)
        self.push_screen(QueryInput(doc_count=len(event.paths)))

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

        while len(self.screen_stack) > 1:
            self.pop_screen()

        self._start_interactive_pipeline()

    # ------------------------------------------------------------------
    # Interactive pipeline execution (TUI mode)
    # ------------------------------------------------------------------

    def _start_interactive_pipeline(self) -> None:
        from ..runner import create_interactive_pipeline
        from .screens.live_pass import LivePassScreen

        self._pipeline, self._history_run_id = create_interactive_pipeline(self._run_config)
        self.push_screen(LivePassScreen(self._pipeline))

    def on_passes_complete(self, event) -> None:
        """All 4 passes done — finalize and show results."""
        from .. import history

        result = self._pipeline.finalize()
        self._result = result

        if hasattr(self, '_history_run_id'):
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

        result = self._result
        self.install_screen(AnswerScreen(result), name="answer")  # type: ignore[arg-type]
        self.install_screen(PassesScreen(result), name="passes")  # type: ignore[arg-type]
        self.install_screen(SystemStateScreen(result), name="system_state")  # type: ignore[arg-type]
        self.install_screen(ConsistencyScreen(result), name="consistency")  # type: ignore[arg-type]

    def _install_history_screens(self) -> None:
        """Install screens from cached history data (no live System)."""
        from .screens.answer import AnswerScreen
        from .screens.passes import PassesScreen

        data = self._history_data
        assert data is not None

        # Build a minimal result-like object for the screens
        hist = _HistoryResult(data)
        self.install_screen(AnswerScreen(hist), name="answer")  # type: ignore[arg-type]
        self.install_screen(PassesScreen(hist), name="passes")  # type: ignore[arg-type]

    def _go_to_answer(self) -> None:
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self.push_screen("answer")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def action_switch_screen(self, screen_name: str) -> None:
        if self._result is None and self._history_data is None:
            return
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self.push_screen(screen_name)

    def action_show_history(self) -> None:
        from .screens.history_browser import HistoryBrowser

        self.push_screen(HistoryBrowser())

    def on_run_selected(self, event) -> None:
        """Handle history run selection."""
        from ..history import get_run

        data = get_run(event.run_id)
        if not data or data["status"] != "completed":
            self.notify("Run has no cached result.", severity="warning")
            return

        self._history_data = data
        self._install_history_screens()
        self._go_to_answer()


class _HistoryResult:
    """Minimal adapter so history data can be used by AnswerScreen / PassesScreen."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.pass1_source = data.get("pass1_source", "")
        self.pass2_source = data.get("pass2_source", "")
        self.pass3_source = data.get("pass3_source", "")
        self.pass4_raw = data.get("pass4_raw", "")
        self.output = _HistoryOutput(data)
        self.system = None  # No live system for history runs


class _HistoryOutput:
    """Minimal adapter for ResolvedOutput from cached data."""

    def __init__(self, data: dict[str, Any]) -> None:
        import json

        self.markdown = data.get("output_md", "")
        self.consistency = data.get("consistency", "")

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
