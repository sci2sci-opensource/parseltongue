"""Shared item-building logic for viz renderers.

Single source of truth for converting probe structure nodes into
the item dicts consumed by the JS detail panel, cards, layers, and graph views.
Both renderer.py and notebook_renderer.py import from here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...probe_core_to_consequence import CoreToConsequenceStructure


def items_from_structure(
    structure: CoreToConsequenceStructure,
    names: set[str] | None = None,
) -> list[dict]:
    """Build item dicts from a probe structure's graph.

    Args:
        structure: probed CoreToConsequenceStructure with .graph and .depths
        names: if given, only include these names. Otherwise include all.

    Returns:
        List of item dicts with id, kind, value, depth, inputs, evidence, module.
    """
    from parseltongue.core.grammar import ParseltongueGrammar

    graph = getattr(structure, "graph", {})
    depths = getattr(structure, "depths", {})
    if not graph:
        return []

    _enc = ParseltongueGrammar.enc
    items = []

    iter_names = sorted(names) if names is not None else sorted(graph)
    for name in iter_names:
        if name.startswith("__"):
            continue
        node = graph.get(name)
        if node is None:
            continue
        kind = node.kind.value if hasattr(node.kind, "value") else str(node.kind)
        depth = depths.get(name, 0)
        inputs = [str(i) for i in (node.inputs or [])]
        module = name.split(".")[0] if "." in name else ""
        value_str = _enc(node.value)
        items.append(
            {
                "id": name,
                "kind": kind,
                "value": value_str,
                "depth": depth,
                "inputs": inputs,
                "evidence": [],
                "module": module,
            }
        )

    return items


def enrich_items(items: list[dict], structure: Any) -> None:
    """Add definition, evidence, and external stubs to items from structure atoms.

    Mutates items in place. Also syncs values: if an item has no value but the
    structure node does, the structure value wins.
    """
    from parseltongue.core.atoms import Axiom, Term, Theorem
    from parseltongue.core.lang import ParseltongueGrammar

    if structure is None:
        return
    graph = getattr(structure, "graph", {})

    for item in items:
        name = item.get("id", "")
        node = graph.get(name)
        if node is None:
            continue

        # Sync value from structure when item has no value
        cur_val = item.get("value", "")
        if not cur_val or cur_val in ("()", "''", '""'):
            struct_val = ParseltongueGrammar.enc(node.value)
            if struct_val and struct_val not in ("()", "''", '""'):
                item["value"] = struct_val

        if node.atom is None:
            continue
        atom = node.atom

        # Definition (WFF string)
        if isinstance(atom, Term) and atom.definition is not None:
            item["definition"] = ParseltongueGrammar.enc(atom.definition)
        elif isinstance(atom, (Axiom, Theorem)) and atom.wff is not None:
            item["definition"] = ParseltongueGrammar.enc(atom.wff)

        # Origin status and evidence
        _enrich_evidence(item, atom)

    # Enrich inputs with in-probe status + create stubs for external graph nodes
    all_ids = {item.get("id", "") for item in items}
    external_needed = set()
    for item in items:
        for inp in item.get("inputs", []):
            inp_name = inp if isinstance(inp, str) else inp.get("name", "")
            if inp_name and inp_name not in all_ids:
                external_needed.add(inp_name)

    # Build stub items for external nodes found in structure graph
    external_items = []
    for ext_name in external_needed:
        ext_node = graph.get(ext_name)
        if ext_node is None:
            continue
        ext_item = {
            "id": ext_name,
            "kind": ext_node.kind.value if hasattr(ext_node.kind, "value") else str(ext_node.kind),
            "value": ParseltongueGrammar.enc(ext_node.value),
            "depth": 0,
            "inputs": [{"name": i, "inProbe": i in all_ids or i in external_needed} for i in ext_node.inputs],
            "evidence": [],
            "module": ext_name.split(".")[0] if "." in ext_name else "",
            "external": True,
        }
        atom = ext_node.atom
        if atom is not None:
            if isinstance(atom, Term) and atom.definition is not None:
                ext_item["definition"] = ParseltongueGrammar.enc(atom.definition)
            elif isinstance(atom, (Axiom, Theorem)) and atom.wff is not None:
                ext_item["definition"] = ParseltongueGrammar.enc(atom.wff)
            _enrich_evidence(ext_item, atom)
        external_items.append(ext_item)
        all_ids.add(ext_name)
    items.extend(external_items)

    # Tag inputs with in-probe status
    for item in items:
        raw_inputs = item.get("inputs", [])
        if raw_inputs and isinstance(raw_inputs[0], str):
            item["inputs"] = [{"name": inp, "inProbe": inp in all_ids} for inp in raw_inputs]


def _enrich_evidence(item: dict, atom: Any) -> None:
    """Extract evidence from an atom's origin into an item dict."""
    from parseltongue.core.atoms import Evidence, Theorem

    origin = getattr(atom, "origin", None)
    if isinstance(origin, Evidence):
        if origin.verified:
            ev_status = "verified"
        elif origin.verify_manual:
            ev_status = "manual"
        else:
            ev_status = "unverified"

        quote_contexts = {}
        quote_details = {}
        for vr in origin.verification or []:
            q = vr.get("quote", "")
            ctx = vr.get("context")
            if q and ctx:
                quote_contexts[q] = {"before": ctx.get("before", ""), "after": ctx.get("after", "")}
            if q:
                detail = {}
                if vr.get("original_line", -1) != -1:
                    detail["line"] = vr["original_line"]
                if vr.get("all_matches"):
                    detail["all_matches"] = vr["all_matches"]
                if vr.get("confidence"):
                    detail["confidence"] = vr["confidence"].get("score")
                if detail:
                    quote_details[q] = detail

        ev_entry = {
            "doc": origin.document,
            "quotes": origin.quotes,
            "quote_contexts": quote_contexts,
            "explanation": origin.explanation,
            "verified": origin.verified,
            "status": ev_status,
            "signature": origin.signature,
        }
        if quote_details:
            ev_entry["quote_details"] = quote_details
        item["evidence"] = [ev_entry]
    elif isinstance(atom, Theorem) or origin == "derived":
        item["evidence"] = [{"status": "derived"}]
    elif isinstance(origin, str) and origin:
        item["evidence"] = [{"doc": origin, "status": "unverified"}]
