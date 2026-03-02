"""Provenance tree widget — recursive evidence chain viewer."""

from __future__ import annotations

from typing import Any

from rich.markup import escape as rich_escape
from textual.widgets import Tree

from parseltongue.core.engine import DiffResult

from .tree_builders import (
    _add_diff_result_leaves,
    _fmt_value,
    add_axiom_node,
    add_fact_node,
    add_origin_node,
    add_term_node,
    add_theorem_node,
    origin_color,
)


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
            self.root.add_leaf(f"[red]Error: {rich_escape(error)}[/red]")
            return

        if value is not None:
            self.root.add_leaf(f"value: {rich_escape(_fmt_value(value))}")

        if provenance:
            self._add_provenance_node(self.root, provenance)

    def show_system_item(self, ref_type: str, ref_name: str, system: Any) -> None:
        """Show a reference by looking it up directly in the live System."""
        self.clear()
        self.root.set_label(rich_escape(f"[[{ref_type}:{ref_name}]]"))
        self.root.expand()

        try:
            prov = system.provenance(ref_name)
            self._add_provenance_node(self.root, prov, system=system)
        except KeyError:
            self.root.add_leaf(f"[red]'{rich_escape(ref_name)}' not found in system[/red]")

    def _add_provenance_node(self, parent, prov: Any, system: Any = None) -> None:
        """Recursively add provenance information to the tree."""
        if not isinstance(prov, dict):
            parent.add_leaf(rich_escape(str(prov)))
            return

        raw_name = str(prov.get("name", "?"))
        ptype = prov.get("type", "?")

        # Use shared renderers when the system has the actual object
        if system is not None:
            if ptype == "term" and raw_name in system.terms:
                add_term_node(parent, raw_name, system.terms[raw_name], system=system)
                return
            if ptype == "fact" and raw_name in system.facts:
                add_fact_node(parent, raw_name, system.facts[raw_name])
                return
            if ptype == "axiom" and raw_name in system.axioms:
                add_axiom_node(parent, raw_name, system.axioms[raw_name])
                return
            if ptype == "theorem" and raw_name in system.theorems:
                add_theorem_node(parent, raw_name, system.theorems[raw_name], system=system)
                # Derivation chain — recurse into provenance for full depth
                chain = prov.get("derivation_chain", [])
                if chain:
                    # Find the theorem node we just added (last child)
                    thm_node = parent.children[-1] if parent.children else parent
                    chain_node = thm_node.add("[bold]derivation chain[/bold]")
                    chain_node.expand()
                    for dep in chain:
                        self._add_provenance_node(chain_node, dep, system=system)
                return

        # Diff type — always uses prov dict for values + recursive provenance
        if ptype == "diff":
            result = DiffResult(
                name=raw_name,
                replace=prov.get("replace", "?"),
                with_=prov.get("with", "?"),
                value_a=prov.get("value_a"),
                value_b=prov.get("value_b"),
                divergences=prov.get("divergences", {}),
            )
            color = "yellow" if result.divergences else "green"
            node = parent.add(f"[{color}][bold]{rich_escape(raw_name)}[/bold] (diff)[/{color}]")
            node.expand()
            _add_diff_result_leaves(node, result, system=system)

            if "provenance_a" in prov:
                pa_node = node.add("[bold]provenance (replace)[/bold]")
                pa_node.expand()
                self._add_provenance_node(pa_node, prov["provenance_a"], system=system)
            if "provenance_b" in prov:
                pb_node = node.add("[bold]provenance (with)[/bold]")
                pb_node.expand()
                self._add_provenance_node(pb_node, prov["provenance_b"], system=system)
            return

        # Fallback: render from prov dict (no system, or unknown type)
        origin = prov.get("origin")
        color = origin_color(origin)
        node = parent.add(f"[{color}][bold]{rich_escape(raw_name)}[/bold] ({rich_escape(str(ptype))})[/{color}]")
        node.expand()
        for key in ("wff", "value", "definition"):
            if key in prov:
                node.add_leaf(f"{key}: {rich_escape(_fmt_value(prov[key]))}")
        if origin:
            add_origin_node(node, origin)
