"""Provenance tree widget — recursive evidence chain viewer."""

from __future__ import annotations

from typing import Any

from rich.markup import escape as rich_escape
from textual.widgets import Tree

from .tree_builders import origin_color


def _prov_origin_color(origin: Any) -> str:
    """Color for a provenance origin (may be dict or str, not Evidence)."""
    if isinstance(origin, dict):
        return "green" if origin.get("grounded") else "red"
    # Fall back to the shared helper for Evidence / str
    return origin_color(origin)


def _add_prov_origin(parent, origin: Any) -> None:
    """Attach origin details from a provenance dict (serialized Evidence)."""
    if isinstance(origin, dict):
        grounded = origin.get("grounded", False)
        if grounded:
            status_tag = "[green]grounded[/green]"
        else:
            status_tag = "[red]UNVERIFIED[/red]"
        doc = origin.get("document", "")
        origin_node = parent.add(f"evidence: {rich_escape(doc)} ({status_tag})")
        for q in origin.get("quotes", []):
            origin_node.add_leaf(f'"{rich_escape(str(q)[:80])}{"..." if len(str(q)) > 80 else ""}"')
        if origin.get("explanation"):
            origin_node.add_leaf(f"explanation: {rich_escape(str(origin['explanation']))}")
        if origin.get("verification"):
            for v in origin["verification"]:
                if isinstance(v, dict):
                    ok = v.get("verified", False)
                    quote = v.get("quote", "")
                    short_q = rich_escape(quote[:60]) + ("..." if len(quote) > 60 else "")
                    if ok:
                        conf = v.get("confidence", {})
                        level = conf.get("level", "?")
                        origin_node.add_leaf(f'[green]"{short_q}" verified ({level})[/green]')
                    else:
                        reason = v.get("reason", "no match")
                        origin_node.add_leaf(f'[red]"{short_q}" NOT verified ({rich_escape(reason)})[/red]')
                else:
                    origin_node.add_leaf(f"verification: {rich_escape(str(v))}")
        if origin.get("verified"):
            origin_node.add_leaf("[green]verified: yes[/green]")
        if origin.get("verify_manual"):
            origin_node.add_leaf("[green]manually verified[/green]")
    elif origin:
        if isinstance(origin, str) and "potential fabrication" in origin:
            parent.add_leaf(f"[red]{rich_escape(origin)}[/red]")
        else:
            parent.add_leaf(f"[yellow]origin: {rich_escape(str(origin))}[/yellow]")


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
            self.root.add_leaf(f"value: {rich_escape(str(value))}")

        if provenance:
            self._add_provenance_node(self.root, provenance)

    def show_system_item(self, ref_type: str, ref_name: str, system: Any) -> None:
        """Show a reference by looking it up directly in the live System."""
        self.clear()
        self.root.set_label(rich_escape(f"[[{ref_type}:{ref_name}]]"))
        self.root.expand()

        try:
            prov = system.provenance(ref_name)
            self._add_provenance_node(self.root, prov)
        except KeyError:
            self.root.add_leaf(f"[red]'{rich_escape(ref_name)}' not found in system[/red]")

    def _add_provenance_node(self, parent, prov: Any) -> None:
        """Recursively add provenance information to the tree."""
        if not isinstance(prov, dict):
            parent.add_leaf(rich_escape(str(prov)))
            return

        name = rich_escape(str(prov.get('name', '?')))
        ptype = prov.get('type', '?')
        origin = prov.get('origin')
        color = _prov_origin_color(origin)

        node = parent.add(f"[{color}][bold]{name}[/bold] ({rich_escape(str(ptype))})[/{color}]")
        node.expand()

        # Show WFF / value / definition
        for key in ('wff', 'value', 'definition'):
            if key in prov:
                node.add_leaf(f"{key}: {rich_escape(str(prov[key]))}")

        # Show origin with full evidence details
        if origin:
            _add_prov_origin(node, origin)

        # Derivation chain (recursive — theorems)
        chain = prov.get('derivation_chain', [])
        if chain:
            chain_node = node.add("[bold]derivation chain[/bold]")
            chain_node.expand()
            for dep in chain:
                self._add_provenance_node(chain_node, dep)

        # Diff-specific fields
        if ptype == 'diff':
            if 'replace' in prov and 'with' in prov:
                node.add_leaf(f"replace: {rich_escape(str(prov['replace']))}")
                node.add_leaf(f"with: {rich_escape(str(prov['with']))}")

            if 'value_a' in prov:
                node.add_leaf(f"value A: {rich_escape(str(prov['value_a']))}")
            if 'value_b' in prov:
                node.add_leaf(f"value B: {rich_escape(str(prov['value_b']))}")

            divergences = prov.get('divergences', {})
            if divergences:
                div_node = node.add(f"[yellow]divergences ({len(divergences)})[/yellow]")
                div_node.expand()
                for term_name, (val_a, val_b) in divergences.items():
                    d = div_node.add(f"[yellow]{rich_escape(term_name)}[/yellow]")
                    d.add_leaf(f"original: {rich_escape(str(val_a))}")
                    d.add_leaf(f"substituted: {rich_escape(str(val_b))}")
            else:
                node.add_leaf("[green]no divergences[/green]")

            # Provenance of both sides (recursive)
            if 'provenance_a' in prov:
                pa_node = node.add("[bold]provenance (replace)[/bold]")
                pa_node.expand()
                self._add_provenance_node(pa_node, prov['provenance_a'])
            if 'provenance_b' in prov:
                pb_node = node.add("[bold]provenance (with)[/bold]")
                pb_node.expand()
                self._add_provenance_node(pb_node, prov['provenance_b'])
