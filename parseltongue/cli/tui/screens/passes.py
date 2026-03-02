"""Passes screen — tabbed view of pipeline pass outputs with state tree."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Label, TabbedContent, TabPane, Tree

from ..widgets.dsl_viewer import DslViewer
from ..widgets.status_bar import StatusBar
from ..widgets.tree_builders import populate_system_tree

if TYPE_CHECKING:
    from parseltongue.llm import PipelineResult

PASS_NAMES = {1: "Extract", 2: "Derive", 3: "Factcheck", 4: "Answer"}


class PassesScreen(Screen):
    """Tabbed view of the four pipeline passes with cumulative state tree."""

    BINDINGS = [
        ("escape", "dismiss", "Back"),
    ]

    def __init__(self, result: PipelineResult, **kwargs) -> None:
        super().__init__(**kwargs)
        self._result = result

    def compose(self) -> ComposeResult:
        with Horizontal(id="passes-layout"):
            with Container(id="passes-dsl-panel"):
                yield Label("Passes", id="passes-title")
                with TabbedContent(id="passes-tabs"):
                    with TabPane("P1: Extract", id="pass-tab-1"):
                        yield DslViewer(self._result.pass1_source or "(empty)")
                    with TabPane("P2: Derive", id="pass-tab-2"):
                        yield DslViewer(self._result.pass2_source or "(empty)")
                    with TabPane("P3: Factcheck", id="pass-tab-3"):
                        yield DslViewer(self._result.pass3_source or "(empty)")
                    with TabPane("P4: Answer", id="pass-tab-4"):
                        yield DslViewer(self._result.pass4_raw or "(empty)")
            with Container(id="passes-state-panel"):
                yield Label("Parseltongue State", id="passes-state-title")
                yield Tree("State", id="passes-state-tree")
        yield StatusBar()

    def on_mount(self) -> None:
        self._refresh_state_tree(1)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        tab_id = event.pane.id or ""
        for i in range(1, 5):
            if tab_id == f"pass-tab-{i}":
                self._refresh_state_tree(i)
                return

    def _refresh_state_tree(self, pass_num: int) -> None:
        tree = self.query_one("#passes-state-tree", Tree)
        tree.clear()
        tree.root.expand()

        # Use stored post-pass snapshots from the interactive run
        pass_systems = getattr(self._result, 'pass_systems', {})
        system = pass_systems.get(pass_num)

        if system is None:
            # Fallback: show final system state
            system = self._result.system

        if system is None:
            tree.root.add_leaf(f"[dim]No state for pass {pass_num}[/dim]")
            return

        populate_system_tree(tree.root, system)
