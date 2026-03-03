"""System state screen — tree browser for facts, terms, axioms, theorems, diffs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Tree

from ..widgets.hints_bar import HintsBar

if TYPE_CHECKING:
    from parseltongue.llm import PipelineResult


class SystemStateScreen(Screen):
    """Browse the formal system: facts, terms, axioms, theorems, diffs."""

    BINDINGS = [
        ("escape", "dismiss", "Back"),
    ]

    def __init__(self, result: PipelineResult, **kwargs) -> None:
        super().__init__(**kwargs)
        self._result = result

    def compose(self) -> ComposeResult:
        tree: Tree = Tree("Parseltongue State")
        tree.root.expand()
        self._populate(tree)
        yield tree
        yield HintsBar(
            [
                ("F1", "Answer", "app.switch_screen('answer')"),
                ("F2", "Passes", "app.switch_screen('passes')"),
                ("F3", "System", "app.switch_screen('system_state')"),
                ("F4", "Consistency", "app.switch_screen('consistency')"),
                ("Esc", "Back", "screen.dismiss"),
            ]
        )

    def _populate(self, tree: Tree) -> None:
        from ..widgets.tree_builders import populate_system_tree

        system = self._result.system
        if system is None:
            tree.root.add_leaf("[dim]No live system (history mode)[/dim]")
            return
        populate_system_tree(tree.root, system)
