"""Reusable tree-node builders for Parseltongue TUI.

Functions here populate Textual Tree nodes for each core language
construct (Term, Axiom, Theorem, Fact, Diff) with full provenance,
grounding colors, and evidence details.  Used by LivePassScreen,
SystemStateScreen, and ProvenanceTree.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from rich.markup import escape as rich_escape

from parseltongue.core.atoms import Evidence, Symbol, to_sexp

# ------------------------------------------------------------------
# Color helpers
# ------------------------------------------------------------------


def _fmt_value(value: Any) -> str:
    """Format a value for display — render S-expressions, str() everything else."""
    if isinstance(value, (list, Symbol)):
        return to_sexp(value)
    return str(value)


def _diff_highlight(a: str, b: str) -> tuple[str, str]:
    """Return (a_markup, b_markup) with changed tokens highlighted green/red."""
    a_tokens = a.split()
    b_tokens = b.split()
    sm = SequenceMatcher(None, a_tokens, b_tokens)
    a_parts: list[str] = []
    b_parts: list[str] = []
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == "equal":
            a_parts.extend(rich_escape(t) for t in a_tokens[a0:a1])
            b_parts.extend(rich_escape(t) for t in b_tokens[b0:b1])
        elif op == "replace":
            a_parts.extend(f"[green]{rich_escape(t)}[/green]" for t in a_tokens[a0:a1])
            b_parts.extend(f"[red]{rich_escape(t)}[/red]" for t in b_tokens[b0:b1])
        elif op == "delete":
            a_parts.extend(f"[green]{rich_escape(t)}[/green]" for t in a_tokens[a0:a1])
        elif op == "insert":
            b_parts.extend(f"[red]{rich_escape(t)}[/red]" for t in b_tokens[b0:b1])
    return " ".join(a_parts), " ".join(b_parts)


def origin_color(origin: Any) -> str:
    """Green = grounded, red = unverified/fabrication, yellow = string origin, white = none."""
    if isinstance(origin, Evidence):
        return "green" if origin.is_grounded else "red"
    if isinstance(origin, dict):
        return "green" if origin.get("grounded") else "red"
    if isinstance(origin, str):
        if "potential fabrication" in origin:
            return "red"
        if origin == "derived":
            return "green"
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
                q_node = origin_node.add(f'[green]"{short_q}" [bold]✓[/bold] {level}[/green]')
            else:
                reason = v.get("reason", "no match")
                q_node = origin_node.add(f'[red]"{short_q}" [bold]✗[/bold] {rich_escape(reason)}[/red]')
            if v.get("context"):
                q_node.add_leaf(f"context: {rich_escape(str(v['context']))}")
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


def add_term_node(parent, name: str, term: Any, system: Any = None) -> None:
    """Add a Term node with evaluated value in title, definition as child."""
    color = origin_color(term.origin)
    val_str = ""
    if system is not None and term.definition is not None:
        try:
            val = system.evaluate(term.definition)
            val_str = f" = {rich_escape(_fmt_value(val))}"
        except (NameError, TypeError):
            pass
    node = parent.add(f"[{color}]{rich_escape(name)}{val_str} [dim](term)[/dim][/{color}]")
    if term.definition is not None:
        node.add_leaf(f"[dim]definition: {rich_escape(to_sexp(term.definition))}[/dim]")
    add_origin_node(node, term.origin)


def add_fact_node(parent, name: str, data: Any) -> None:
    """Add a Fact node with value and origin."""
    val = data.get("value", data) if isinstance(data, dict) else data
    origin = data.get("origin") if isinstance(data, dict) else None
    color = origin_color(origin)
    node = parent.add(f"[{color}]{rich_escape(str(name))} = {rich_escape(_fmt_value(val))} [dim](fact)[/dim][/{color}]")
    if origin:
        add_origin_node(node, origin)


def add_axiom_node(parent, name: str, axiom: Any) -> None:
    """Add an Axiom node with wff and origin."""
    color = origin_color(axiom.origin)
    node = parent.add(f"[{color}]{rich_escape(name)}: {rich_escape(to_sexp(axiom.wff))} [dim](axiom)[/dim][/{color}]")
    add_origin_node(node, axiom.origin)


def add_theorem_node(parent, name: str, thm: Any, system: Any = None) -> None:
    """Add a Theorem node with wff, derivation chain, and origin."""
    color = origin_color(thm.origin)
    node = parent.add(f"[{color}]{rich_escape(name)}: {rich_escape(to_sexp(thm.wff))} [dim](theorem)[/dim][/{color}]")
    if thm.derivation:
        deriv_node = node.add(f"derived from: {', '.join(rich_escape(d) for d in thm.derivation)}")
        if system is not None:
            for d in thm.derivation:
                defn = _item_definition(d, system)
                if defn:
                    deriv_node.add_leaf(f"[dim]{rich_escape(d)}: {rich_escape(defn)}[/dim]")
    add_origin_node(node, thm.origin)


def _item_definition(name: str, system: Any) -> str | None:
    """Look up the definition/formula for any system item by name."""
    if name in system.terms:
        defn = system.terms[name].definition
        if defn is not None:
            return to_sexp(defn)
    if name in system.axioms:
        return to_sexp(system.axioms[name].wff)
    if name in system.theorems:
        return to_sexp(system.theorems[name].wff)
    if name in system.facts:
        data = system.facts[name]
        val = data.get("value", data) if isinstance(data, dict) else data
        return _fmt_value(val)
    return None


def _add_definition_leaf(node, name: str, system: Any) -> None:
    """Add a dim definition leaf for *name* if the system knows its formula."""
    if system is None:
        return
    defn = _item_definition(name, system)
    if defn:
        node.add_leaf(f"[dim]definition: {rich_escape(defn)}[/dim]")


def _add_named_leaf(node, label: str, name: str, system: Any = None) -> None:
    """Add a leaf showing 'label: name' with definition as child if available."""
    n = node.add(f"{label}: {rich_escape(name)}")
    _add_definition_leaf(n, name, system)


def _add_diff_result_leaves(node, result: Any, system: Any = None) -> None:
    """Render an evaluated DiffResult's values and divergences into *node*."""
    sa, sb = _fmt_value(result.value_a), _fmt_value(result.value_b)
    ha, hb = _diff_highlight(sa, sb)
    a_node = node.add(f"replace ({rich_escape(result.replace)}): {ha}")
    _add_definition_leaf(a_node, result.replace, system)
    b_node = node.add(f"with ({rich_escape(result.with_)}): {hb}")
    _add_definition_leaf(b_node, result.with_, system)

    if result.divergences:
        div_node = node.add(f"[yellow]divergences ({len(result.divergences)})[/yellow]")
        div_node.expand()
        for term_name, (val_a, val_b) in result.divergences.items():
            d = div_node.add(f"[yellow]{rich_escape(term_name)}[/yellow]")
            _add_definition_leaf(d, term_name, system)
            da, db = _diff_highlight(_fmt_value(val_a), _fmt_value(val_b))
            d.add_leaf(f"original: {da}")
            d.add_leaf(f"substituted: {db}")
    elif hasattr(result, "values_diverge") and result.values_diverge:
        node.add_leaf("[yellow]values differ (no downstream affected)[/yellow]")
    else:
        node.add_leaf("[green]no divergences[/green]")


def add_diff_result_node(parent, result: Any, system: Any = None) -> None:
    """Add a pre-evaluated DiffResult as a tree node (used by consistency screen)."""
    color = "yellow" if result.divergences or result.values_diverge else "green"
    node = parent.add(f"[{color}]Diff Divergence: {rich_escape(result.name)}[/{color}]")
    _add_diff_result_leaves(node, result, system=system)


def add_diff_node(parent, name: str, diff: dict, system: Any = None) -> None:
    """Add a Diff node with evaluated values, divergences, and provenance."""
    replace_name = str(diff.get("replace", "?"))
    with_name = str(diff.get("with", "?"))
    if system is not None:
        try:
            result = system.eval_diff(name)
            has_divergences = bool(result.divergences) or result.values_diverge
        except Exception:
            result = None
            has_divergences = False
    else:
        result = None
        has_divergences = False

    color = "yellow" if has_divergences else "green"
    label = f"[{color}]{rich_escape(name)}: {rich_escape(replace_name)} vs {rich_escape(with_name)}[/{color}]"
    node = parent.add(label)

    if result is not None:
        _add_diff_result_leaves(node, result, system=system)
    else:
        _add_named_leaf(node, "replace", replace_name, system)
        _add_named_leaf(node, "with", with_name, system)


# ------------------------------------------------------------------
# Full system tree population
# ------------------------------------------------------------------


def populate_system_tree(tree_root, system: Any) -> None:
    """Populate a Tree root node with the full system state."""
    if system.facts:
        section = tree_root.add("[bold]Facts[/bold]", expand=True)
        for name, data in system.facts.items():
            add_fact_node(section, name, data)

    if system.terms:
        section = tree_root.add("[bold]Terms[/bold]", expand=True)
        for name, term in system.terms.items():
            add_term_node(section, name, term, system=system)

    if system.axioms:
        section = tree_root.add("[bold]Axioms[/bold]", expand=True)
        for name, axiom in system.axioms.items():
            add_axiom_node(section, name, axiom)

    if system.theorems:
        section = tree_root.add("[bold]Theorems[/bold]", expand=True)
        for name, thm in system.theorems.items():
            add_theorem_node(section, name, thm, system=system)

    if system.diffs:
        section = tree_root.add("[bold]Diffs[/bold]", expand=True)
        for name, diff in system.diffs.items():
            add_diff_node(section, name, diff, system=system)
