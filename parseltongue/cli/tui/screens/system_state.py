"""System state screen — tree browser for facts, terms, axioms, theorems, diffs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.screen import Screen

from ..widgets import FocusedTree
from ..widgets.hints_bar import HintsBar

if TYPE_CHECKING:
    from parseltongue.llm import PipelineResult


class SystemStateScreen(Screen):
    """Browse the formal system: facts, terms, axioms, theorems, diffs."""

    BINDINGS = [
        ("f1", "app.switch_screen('answer')", "Answer"),
        ("f2", "app.switch_screen('passes')", "Passes"),
        ("f3", "app.switch_screen('system_state')", "System"),
        ("f4", "app.switch_screen('consistency')", "Consistency"),
        ("f5", "app.show_history", "History"),
        ("f6", "app.main_menu", "Menu"),
        ("escape", "dismiss", "Back"),
    ]

    HINTS: list[tuple[str, ...]] = [
        ("F1", "Answer", "app.switch_screen('answer')"),
        ("F2", "Passes", "app.switch_screen('passes')"),
        ("F3", "System", "app.switch_screen('system_state')"),
        ("F4", "Consistency", "app.switch_screen('consistency')"),
        ("Esc", "Back", "screen.dismiss"),
    ]

    def __init__(self, result: PipelineResult, **kwargs) -> None:
        super().__init__(**kwargs)
        self._result = result

    def compose(self) -> ComposeResult:
        tree = FocusedTree("Parseltongue State", id="system-tree", require_focus=False)
        tree.root.expand()
        self._populate(tree)
        yield tree
        yield HintsBar(self.HINTS)

    def _populate(self, tree: Any) -> None:
        from ..widgets.tree_builders import populate_system_tree

        system = self._result.system
        if system is None:
            tree.root.add_leaf("[dim]No live system (history mode)[/dim]")
            return
        populate_system_tree(tree.root, system)
