"""Passes screen — tabbed view of pipeline pass outputs with state tree."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Label, Static, TabbedContent, TabPane, Tree

from ..widgets.hints_bar import HintsBar
from ..widgets.pass_viewer import PassViewer
from ..widgets.resizable_split import ResizableSplitMixin
from ..widgets.tree_builders import populate_system_tree

if TYPE_CHECKING:
    from parseltongue.llm import PipelineResult

PASS_NAMES = {1: "Extract", 2: "Derive", 3: "Factcheck", 4: "Answer"}


class PassesScreen(ResizableSplitMixin, Screen):
    """Tabbed view of the four pipeline passes with cumulative state tree."""

    _split_grid_id = "passes-layout"

    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("ctrl+y", "copy_pass", "Copy pass"),
        ("f9", "grow_right", "F9 Grow right"),
        ("f10", "grow_left", "F10 Grow left"),
    ]

    def __init__(self, result: PipelineResult, **kwargs) -> None:
        super().__init__(**kwargs)
        self._result = result

    def compose(self) -> ComposeResult:
        with Horizontal(id="passes-layout"):
            with Container(id="passes-dsl-panel"):
                with Horizontal(id="passes-header"):
                    yield Label("Passes", id="passes-title")
                    yield Static("[@click=screen.copy_pass]Copy[/]", id="passes-copy-btn")
                with TabbedContent(id="passes-tabs"):
                    with TabPane("P1: Extract", id="pass-tab-1"):
                        yield PassViewer(
                            self._result.pass1_source or "(empty)",
                        )
                    with TabPane("P2: Derive", id="pass-tab-2"):
                        yield PassViewer(
                            self._result.pass2_source or "(empty)",
                        )
                    with TabPane("P3: Factcheck", id="pass-tab-3"):
                        yield PassViewer(
                            self._result.pass3_source or "(empty)",
                        )
                    with TabPane("P4: Answer", id="pass-tab-4"):
                        yield PassViewer(
                            self._result.pass4_raw or "(empty)",
                            language="markdown",
                        )
            with Container(id="passes-state-panel"):
                yield Label("Parseltongue State", id="passes-state-title")
                yield Tree("State", id="passes-state-tree")
        yield HintsBar(
            [
                ("F1", "Answer", "app.switch_screen('answer')"),
                ("F2", "Passes", "app.switch_screen('passes')"),
                ("F3", "System", "app.switch_screen('system_state')"),
                ("F4", "Consistency", "app.switch_screen('consistency')"),
                ("Ctrl+Y", "Copy", "screen.copy_pass"),
                ("F9", "Grow right", "screen.grow_right"),
                ("F10", "Grow left", "screen.grow_left"),
                ("Esc", "Back", "screen.dismiss"),
            ]
        )

    def on_mount(self) -> None:
        self._refresh_state_tree(1)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        tab_id = event.pane.id or ""
        for i in range(1, 5):
            if tab_id == f"pass-tab-{i}":
                self._refresh_state_tree(i)
                return

    def action_copy_pass(self) -> None:
        """Copy the active tab's pass content to clipboard."""
        import subprocess

        tabs = self.query_one("#passes-tabs", TabbedContent)
        tab_id = tabs.active
        try:
            pane = self.query_one(f"#{tab_id}", TabPane)
            viewer = pane.query_one(PassViewer)
            text = viewer.plain_text
        except Exception:
            text = ""
        try:
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
        except Exception:
            self.app.copy_to_clipboard(text)
        self.notify("Pass copied to clipboard.")

    def action_ref_clicked(self, ref_type: str, ref_name: str) -> None:
        """Handle @click from PassViewer refs."""
        tree = self.query_one("#passes-state-tree", Tree)
        tree.root.expand()
        for node in tree.root.children:
            node.expand()
            for child in node.children:
                plain = re.sub(r"\[/?[^\]]*\]", "", str(child.label))
                if plain.startswith(ref_name + ":") or plain.startswith(ref_name + " ="):
                    child.toggle()
                    tree.move_cursor(child)
                    tree.focus()
                    return
        self.notify(
            f"{ref_type}:{ref_name} not in state tree.",
            severity="warning",
        )

    def _refresh_state_tree(self, pass_num: int) -> None:
        tree = self.query_one("#passes-state-tree", Tree)
        tree.clear()
        tree.root.expand()

        pass_systems = getattr(self._result, "pass_systems", {})
        system = pass_systems.get(pass_num)

        if system is None:
            system = self._result.system

        if system is None:
            tree.root.add_leaf(f"[dim]No state for pass {pass_num}[/dim]")
            return

        populate_system_tree(tree.root, system)
