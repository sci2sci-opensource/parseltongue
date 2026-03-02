"""Passes screen — tabbed view of pipeline pass outputs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import TabbedContent, TabPane

from ..widgets.dsl_viewer import DslViewer
from ..widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from parseltongue.llm import PipelineResult


class PassesScreen(Screen):
    """Tabbed view of the four pipeline passes."""

    def __init__(self, result: PipelineResult, **kwargs) -> None:
        super().__init__(**kwargs)
        self._result = result

    def compose(self) -> ComposeResult:
        with TabbedContent():
            with TabPane("Pass 1: Extract"):
                yield DslViewer(self._result.pass1_source or "(empty)")
            with TabPane("Pass 2: Derive"):
                yield DslViewer(self._result.pass2_source or "(empty)")
            with TabPane("Pass 3: Factcheck"):
                yield DslViewer(self._result.pass3_source or "(empty)")
            with TabPane("Pass 4: Answer"):
                yield DslViewer(self._result.pass4_raw or "(empty)")
        yield StatusBar()
