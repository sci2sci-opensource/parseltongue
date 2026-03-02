"""Provenance tree widget — recursive evidence chain viewer."""

from __future__ import annotations

from typing import Any

from rich.markup import escape as rich_escape
from textual.widgets import Tree


class ProvenanceTree(Tree):
    """Tree widget that displays the provenance chain for a reference."""

    def __init__(self, **kwargs) -> None:
        super().__init__("Provenance", **kwargs)

    def show_provenance(self, provenance: dict) -> None:
        """Populate the tree from a provenance dict."""
        self.clear()
        self.root.expand()
        self._add_provenance_node(self.root, provenance)

    def show_reference(
        self,
        ref_type: str,
        ref_name: str,
        value: Any = None,
        provenance: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Show a reference with its value and provenance."""
        self.clear()
        self.root.set_label(rich_escape(f"[[{ref_type}:{ref_name}]]"))
        self.root.expand()

        if error:
            self.root.add_leaf(f"[red]Error: {error}[/red]")
            return

        if value is not None:
            self.root.add_leaf(f"value: {rich_escape(str(value))}")

        if provenance:
            self._add_provenance_node(self.root, provenance)

    def _add_provenance_node(self, parent, prov: dict) -> None:
        """Recursively add provenance information to the tree."""
        if not isinstance(prov, dict):
            parent.add_leaf(rich_escape(str(prov)))
            return

        name = rich_escape(str(prov.get('name', '?')))
        ptype = rich_escape(str(prov.get('type', '?')))

        node = parent.add(f"[bold]{name}[/bold] ({ptype})")
        node.expand()

        # Show WFF / value / definition
        for key in ('wff', 'value', 'definition'):
            if key in prov:
                node.add_leaf(f"{key}: {rich_escape(str(prov[key]))}")

        # Show origin
        origin = prov.get('origin')
        if origin:
            if isinstance(origin, dict):
                origin_node = node.add("origin")
                origin_node.expand()
                doc = origin.get('document', '')
                if doc:
                    origin_node.add_leaf(f"document: {doc}")
                quotes = origin.get('quotes', [])
                for q in quotes:
                    origin_node.add_leaf(f'"{rich_escape(str(q))}"')
                verified = origin.get('verified', False)
                status = "[green]verified[/green]" if verified else "[yellow]unverified[/yellow]"
                origin_node.add_leaf(f"status: {status}")
                explanation = origin.get('explanation', '')
                if explanation:
                    origin_node.add_leaf(f"explanation: {rich_escape(str(explanation))}")
            else:
                node.add_leaf(f"origin: {rich_escape(str(origin))}")

        # Derivation chain (recursive)
        chain = prov.get('derivation_chain', [])
        if chain:
            chain_node = node.add("derivation chain")
            chain_node.expand()
            for dep in chain:
                self._add_provenance_node(chain_node, dep)
