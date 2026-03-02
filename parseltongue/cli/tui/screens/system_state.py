"""System state screen — tree browser for facts, terms, axioms, theorems, diffs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Tree

from ..widgets.status_bar import StatusBar

if TYPE_CHECKING:
    from parseltongue.llm import PipelineResult


class SystemStateScreen(Screen):
    """Browse the formal system: facts, terms, axioms, theorems, diffs."""

    def __init__(self, result: PipelineResult, **kwargs) -> None:
        super().__init__(**kwargs)
        self._result = result

    def compose(self) -> ComposeResult:
        tree: Tree = Tree("System State")
        tree.root.expand()
        self._populate(tree)
        yield tree
        yield StatusBar()

    def _populate(self, tree: Tree) -> None:
        system = self._result.system

        # Facts
        if system.facts:
            facts_node = tree.root.add("Facts", expand=True)
            for name, data in system.facts.items():
                val = data.get('value', data) if isinstance(data, dict) else data
                origin = data.get('origin', '') if isinstance(data, dict) else ''
                node = facts_node.add(f"{name} = {val}")
                if origin:
                    node.add_leaf(f"origin: {origin}")

        # Terms
        if system.terms:
            terms_node = tree.root.add("Terms", expand=True)
            for name, term in system.terms.items():
                node = terms_node.add(f"{name}")
                node.add_leaf(f"definition: {term.definition}")
                node.add_leaf(f"origin: {term.origin}")

        # Axioms
        if system.axioms:
            axioms_node = tree.root.add("Axioms", expand=True)
            for name, axiom in system.axioms.items():
                node = axioms_node.add(f"{name}")
                node.add_leaf(f"wff: {axiom.wff}")
                node.add_leaf(f"origin: {axiom.origin}")

        # Theorems
        if system.theorems:
            theorems_node = tree.root.add("Theorems", expand=True)
            for name, theorem in system.theorems.items():
                node = theorems_node.add(f"{name}")
                node.add_leaf(f"wff: {theorem.wff}")
                node.add_leaf(f"derivation: {theorem.derivation}")
                node.add_leaf(f"origin: {theorem.origin}")

        # Diffs
        if system.diffs:
            diffs_node = tree.root.add("Diffs", expand=True)
            for name, diff in system.diffs.items():
                node = diffs_node.add(f"{name}")
                node.add_leaf(f"replace: {diff.get('replace', '?')}")
                node.add_leaf(f"with: {diff.get('with', '?')}")
