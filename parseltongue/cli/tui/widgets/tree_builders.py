"""Reusable tree-node builders for Parseltongue TUI.

Functions here populate Textual Tree nodes for each core language
construct (Term, Axiom, Theorem, Fact, Diff) with full provenance,
grounding colors, and evidence details.  Used by LivePassScreen,
SystemStateScreen, and ProvenanceTree.
"""

from __future__ import annotations

from typing import Any

from rich.markup import escape as rich_escape

from parseltongue.core.atoms import Evidence, to_sexp

# ------------------------------------------------------------------
# Color helpers
# ------------------------------------------------------------------


def origin_color(origin: Any) -> str:
    """Green = grounded, red = unverified/fabrication, yellow = string origin, white = none."""
    if isinstance(origin, Evidence):
        return "green" if origin.is_grounded else "red"
    if isinstance(origin, dict):
        return "green" if origin.get("grounded") else "red"
    if isinstance(origin, str) and "potential fabrication" in origin:
        return "red"
    if origin:
        return "yellow"
    return "white"


# ------------------------------------------------------------------
# Origin / evidence node
# ------------------------------------------------------------------


def add_evidence_node(
    parent, document: str, grounded: bool, quotes: list, verification: list | None, explanation: str | None
) -> None:
    """Render evidence with quotes and verification into tree nodes.

    Shared by add_origin_node (Evidence objects) and provenance_tree
    (_add_prov_origin, serialized dicts).
    """
    status_tag = "[green]grounded[/green]" if grounded else "[red]UNVERIFIED[/red]"
    origin_node = parent.add(f"evidence: {rich_escape(document)} ({status_tag})")
    if explanation:
        origin_node.add_leaf(f"explanation: {rich_escape(str(explanation))}")
    verif_map: dict[str, dict] = {}
    if verification:
        for v in verification:
            if isinstance(v, dict):
                verif_map[v.get("quote", "")] = v
    for q in quotes:
        q_str = str(q)
        short_q = rich_escape(q_str[:80]) + ("..." if len(q_str) > 80 else "")
        v = verif_map.get(q_str)
        if v:
            ok = v.get("verified", False)
            if ok:
                conf = v.get("confidence", {})
                level = conf.get("level", "?")
                q_node = origin_node.add(f'[green]"{short_q}" ({level})[/green]')
            else:
                reason = v.get("reason", "no match")
                q_node = origin_node.add(f'[red]"{short_q}" NOT verified ({rich_escape(reason)})[/red]')
            if v.get("context"):
                q_node.add_leaf(f"context: {rich_escape(str(v['context'])[:120])}")
            if len(q_str) > 80:
                q_node.add_leaf(f'full: "{rich_escape(q_str)}"')
        else:
            origin_node.add_leaf(f'"{short_q}"')


def add_origin_node(parent, origin: Any) -> None:
    """Attach evidence or plain-string origin as child nodes."""
    if isinstance(origin, Evidence):
        add_evidence_node(
            parent,
            document=origin.document,
            grounded=origin.is_grounded,
            quotes=origin.quotes,
            verification=origin.verification,
            explanation=origin.explanation,
        )
    elif isinstance(origin, dict):
        add_evidence_node(
            parent,
            document=origin.get("document", ""),
            grounded=origin.get("grounded", False),
            quotes=origin.get("quotes", []),
            verification=origin.get("verification"),
            explanation=origin.get("explanation"),
        )
    elif origin:
        if isinstance(origin, str) and "potential fabrication" in origin:
            parent.add_leaf(f"[red]{rich_escape(origin)}[/red]")
        else:
            parent.add_leaf(f"[yellow]origin: {rich_escape(str(origin))}[/yellow]")


# ------------------------------------------------------------------
# Per-construct node builders
# ------------------------------------------------------------------


def add_term_node(parent, name: str, term: Any) -> None:
    """Add a Term node with definition and origin."""
    defn = to_sexp(term.definition) if term.definition is not None else "(primitive)"
    color = origin_color(term.origin)
    node = parent.add(f"[{color}]{rich_escape(name)}: {rich_escape(defn)}[/{color}]")
    add_origin_node(node, term.origin)


def add_fact_node(parent, name: str, data: Any) -> None:
    """Add a Fact node with value and origin."""
    val = data.get("value", data) if isinstance(data, dict) else data
    origin = data.get("origin") if isinstance(data, dict) else None
    color = origin_color(origin)
    node = parent.add(f"[{color}]{rich_escape(str(name))} = {rich_escape(str(val))}[/{color}]")
    if origin:
        add_origin_node(node, origin)


def add_axiom_node(parent, name: str, axiom: Any) -> None:
    """Add an Axiom node with wff and origin."""
    color = origin_color(axiom.origin)
    node = parent.add(f"[{color}]{rich_escape(name)}: {rich_escape(to_sexp(axiom.wff))}[/{color}]")
    add_origin_node(node, axiom.origin)


def add_theorem_node(parent, name: str, thm: Any) -> None:
    """Add a Theorem node with wff, derivation chain, and origin."""
    color = origin_color(thm.origin)
    node = parent.add(f"[{color}]{rich_escape(name)}: {rich_escape(to_sexp(thm.wff))}[/{color}]")
    if thm.derivation:
        node.add_leaf(f"derived from: {', '.join(rich_escape(d) for d in thm.derivation)}")
    add_origin_node(node, thm.origin)


def add_diff_node(parent, name: str, diff: dict, system: Any = None) -> None:
    """Add a Diff node with evaluated values, divergences, and provenance."""
    replace_name = str(diff.get("replace", "?"))
    with_name = str(diff.get("with", "?"))
    if system is not None:
        try:
            result = system.eval_diff(name)
            has_divergences = bool(result.divergences)
        except Exception:
            result = None
            has_divergences = False
    else:
        result = None
        has_divergences = False

    color = "yellow" if has_divergences else "green"
    label = f"[{color}]{rich_escape(name)}: {rich_escape(replace_name)} vs {rich_escape(with_name)}[/{color}]"
    node = parent.add(label)
    node.add_leaf(f"replace: {rich_escape(replace_name)}")
    node.add_leaf(f"with: {rich_escape(with_name)}")

    if result is None:
        return

    node.add_leaf(f"value A: {rich_escape(str(result.value_a))}")
    node.add_leaf(f"value B: {rich_escape(str(result.value_b))}")

    if result.divergences:
        div_node = node.add(f"[yellow]divergences ({len(result.divergences)})[/yellow]")
        div_node.expand()
        for term_name, (val_a, val_b) in result.divergences.items():
            d = div_node.add(f"[yellow]{rich_escape(term_name)}[/yellow]")
            d.add_leaf(f"original: {rich_escape(str(val_a))}")
            d.add_leaf(f"substituted: {rich_escape(str(val_b))}")
    else:
        node.add_leaf("[green]no divergences[/green]")


# ------------------------------------------------------------------
# Full system tree population
# ------------------------------------------------------------------


def populate_system_tree(tree_root, system: Any) -> None:
    """Populate a Tree root node with the full system state."""
    if system.terms:
        section = tree_root.add("[bold]Terms[/bold]", expand=True)
        for name, term in system.terms.items():
            add_term_node(section, name, term)

    if system.facts:
        section = tree_root.add("[bold]Facts[/bold]", expand=True)
        for name, data in system.facts.items():
            add_fact_node(section, name, data)

    if system.axioms:
        section = tree_root.add("[bold]Axioms[/bold]", expand=True)
        for name, axiom in system.axioms.items():
            add_axiom_node(section, name, axiom)

    if system.theorems:
        section = tree_root.add("[bold]Theorems[/bold]", expand=True)
        for name, thm in system.theorems.items():
            add_theorem_node(section, name, thm)

    if system.diffs:
        section = tree_root.add("[bold]Diffs[/bold]", expand=True)
        for name, diff in system.diffs.items():
            add_diff_node(section, name, diff, system=system)
