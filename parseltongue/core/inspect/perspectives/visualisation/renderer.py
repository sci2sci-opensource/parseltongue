"""VizRenderer — FormRenderer that produces self-contained HTML.

(fmt "viz" form) → HTML string with interactive exploration UI.
(fmt "viz" scalar) → HTML with syntax-highlighted s-expression.

Default view: grouped card layout with search, kind filters, evidence panel.
Toggle: D3 force graph for subsets where connections matter.

Caching: Store holds rendered HTML keyed by content hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Any

from ...form_renderer import FormRenderer, _to_sexp

log = logging.getLogger("parseltongue.viz")

if TYPE_CHECKING:
    from ...probe_core_to_consequence import CoreToConsequenceStructure
    from ...store import Store

# ── Template loading ──

_TEMPLATES = Path(__file__).parent / "templates"


def _read_template(name: str) -> str:
    return (_TEMPLATES / name).read_text()


class VizRenderer(FormRenderer):
    """Tailwind + D3 renderer for bench forms."""

    def __init__(
        self,
        store: "Store | None" = None,
        merkle_root: str = "",
        structure: "Any | None" = None,
        loc_fn: "Callable[[str], str] | None" = None,
        diff_structure: "Any | None" = None,
    ):
        self._store = store
        self._merkle_root = merkle_root
        self._structure = structure  # CoreToConsequenceStructure for rail layout
        self._loc_fn = loc_fn
        self._diff_structure = diff_structure  # from probe_diffs_to_possibilities

    def fmt(self, val: Any) -> str:
        key = _content_hash(_to_sexp(val))
        if self._store and self._merkle_root:
            cached = self._store.load_viz(self._merkle_root, key)
            if cached is not None:
                return cached
        result = super().fmt(val)
        if self._store and self._merkle_root:
            self._store.save_viz(self._merkle_root, key, str(result))
        return result

    @property
    def _logbook(self) -> list[dict]:
        if self._store:
            return self._store.read_logbook()
        return []

    def render_form(self, form: list) -> str:
        tag = _base_tag(form)
        ds = self._diff_structure
        if tag in ("ln", "ln-fmt"):
            return _render_app(
                _extract_ln_items([form]),
                "ln",
                _ln_title(form),
                self._structure,
                logbook=self._logbook,
                diff_structure=ds,
            )
        if tag in ("sr", "sr-fmt"):
            return _render_app(
                _extract_sr_items([form]),
                "sr",
                "Search result",
                self._structure,
                logbook=self._logbook,
                diff_structure=ds,
            )
        if tag in ("dx", "dx-fmt"):
            return _render_app(
                _extract_dx_items([form]), "dx", "Diagnostic", self._structure, logbook=self._logbook, diff_structure=ds
            )
        if tag in ("hn", "hn-fmt"):
            return _render_app(
                _extract_hn_items([form]), "hn", "Hologram", self._structure, logbook=self._logbook, diff_structure=ds
            )
        if tag == "df":
            df_item = _extract_df_item(form)
            items = [df_item] if df_item is not None else []
            return _render_app(items, "hn", "Diff", self._structure, logbook=self._logbook, diff_structure=ds)
        return self.fmt_value(form)

    def render_form_list(self, forms: list[list]) -> str:
        if not forms:
            return self.fmt_value([])
        tag = _base_tag(forms[0])
        n = len(forms)
        ds = self._diff_structure
        if tag in ("ln", "ln-fmt"):
            return _render_app(
                _extract_ln_items(forms), "ln", f"{n} nodes", self._structure, logbook=self._logbook, diff_structure=ds
            )
        if tag in ("sr", "sr-fmt"):
            return _render_app(
                _extract_sr_items(forms),
                "sr",
                f"{n} results",
                self._structure,
                logbook=self._logbook,
                diff_structure=ds,
            )
        if tag in ("dx", "dx-fmt"):
            return _render_app(
                _extract_dx_items(forms),
                "dx",
                f"{n} diagnostics",
                self._structure,
                logbook=self._logbook,
                diff_structure=ds,
            )
        if tag in ("hn", "hn-fmt", "df"):
            hn_forms = [f for f in forms if _base_tag(f) in ("hn", "hn-fmt")]
            df_forms = [f for f in forms if _base_tag(f) == "df"]
            items = _extract_hn_items(hn_forms)
            for df in df_forms:
                df_item = _extract_df_item(df)
                if df_item is not None:
                    items.insert(0, df_item)
            return _render_app(
                items,
                "hn",
                f"{len(items)} holograms",
                self._structure,
                logbook=self._logbook,
                diff_structure=ds,
            )
        return self.fmt_value(forms)

    def fmt_value(self, val: Any) -> str:
        sexp = _to_sexp(val)
        tmpl = Template(_read_template("highlight.html"))
        return tmpl.safe_substitute(content=_html_escape(sexp))


# ── Helpers ──


def _base_tag(form: list | tuple) -> str:
    if not form:
        return ""
    return str(form[0]).rsplit(".", 1)[-1]


def _content_hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Data extraction ──


def _extract_ln_items(forms: list[list]) -> list[dict]:
    """ln/ln-fmt forms → list of item dicts for the template."""
    items = []
    seen = set()
    for form in forms:
        f = form[1:]
        if _base_tag(form) == "ln-fmt" and len(f) >= 2:
            f = f[1:]
        if not f:
            continue
        name = str(f[0])
        if name in seen:
            continue
        seen.add(name)
        kind = str(f[1]) if len(f) > 1 else ""
        value = str(f[2]) if len(f) > 2 else ""
        depth = int(f[3]) if len(f) > 3 and isinstance(f[3], (int, float)) else 0
        inputs = [str(x) for x in f[4]] if len(f) > 4 and isinstance(f[4], list) else []
        # Evidence: ln-ev sublists
        evidence = []
        ev_list = f[5] if len(f) > 5 and isinstance(f[5], (list, tuple)) else None
        if ev_list and len(ev_list) >= 2:
            tag_ev = str(ev_list[0]).rsplit(".", 1)[-1] if ev_list else ""
            if tag_ev == "ln-ev":
                ev = ev_list[1:]
                evidence.append(
                    {
                        "doc": str(ev[0]) if ev else "",
                        "quote": str(ev[1]) if len(ev) > 1 else "",
                        "label": str(ev[2]) if len(ev) > 2 else "",
                        "verified": bool(ev[3]) if len(ev) > 3 else False,
                    }
                )
        module = name.split(".")[0] if "." in name else ""
        items.append(
            {
                "id": name,
                "kind": kind,
                "value": value,
                "depth": depth,
                "inputs": inputs,
                "evidence": evidence,
                "module": module,
            }
        )
    return items


def _extract_sr_items(forms: list[list]) -> list[dict]:
    items = []
    for form in forms:
        f = form[1:]
        if _base_tag(form) == "sr-fmt" and len(f) >= 2:
            f = f[1:]
        if not f:
            continue
        doc = str(f[0])
        line = str(f[1]) if len(f) > 1 else "0"
        # Find context (first str after line) and callers (last list)
        ctx = ""
        callers_raw: list = []
        for el in f[2:]:
            if isinstance(el, str):
                ctx = el
            elif isinstance(el, (list, tuple)):
                callers_raw = list(el)
            # skip int (column)
        callers = []
        for c in callers_raw:
            if isinstance(c, (list, tuple)) and len(c) >= 2:
                callers.append({"name": str(c[0]), "overlap": float(c[1])})
            elif isinstance(c, str):
                callers.append({"name": c, "overlap": 1.0})
        items.append({"doc": doc, "line": line, "ctx": ctx, "callers": callers, "module": doc})
    return items


def _extract_dx_items(forms: list[list]) -> list[dict]:
    items = []
    for form in forms:
        f = form[1:]
        if _base_tag(form) == "dx-fmt" and len(f) >= 2:
            f = f[1:]
        if not f:
            continue
        name = str(f[0])
        cat = str(f[1]) if len(f) > 1 else "unknown"
        kind = str(f[2]) if len(f) > 2 else ""
        typ = str(f[3]) if len(f) > 3 else ""
        detail = str(f[4]) if len(f) > 4 else ""
        items.append({"id": name, "category": cat, "kind": kind, "type": typ, "detail": detail, "module": cat})
    return items


def _fmt_wff(val) -> str:
    """Format a WFF value for display — encode s-expressions, passthrough strings."""
    if isinstance(val, str):
        return val
    try:
        from parseltongue.core.grammar import ParseltongueGrammar
        from parseltongue.core.serialization import deserialize_sexp

        return ParseltongueGrammar.enc(deserialize_sexp(val))
    except Exception:
        return str(val)


def split_divergences(divergences: dict) -> tuple[dict[str, dict], dict[str, dict], bool]:
    """Split raw divergences into real vs contaminated and compute coherence-readiness.

    Returns (real_divs, contaminated, has_real_divergences).
    Contaminated entries have an ``after`` value starting with ``<contaminated:``.
    """
    real_divs: dict[str, dict] = {}
    contaminated: dict[str, dict] = {}
    for dn, dv in divergences.items():
        if isinstance(dv, (list, tuple)) and len(dv) >= 2:
            before, after = _fmt_wff(dv[0]), _fmt_wff(dv[1])
        else:
            before, after = _fmt_wff(dv), ""
        if after.startswith("<contaminated:"):
            contaminated[dn] = {"before": before, "after": after}
        else:
            real_divs[dn] = {"before": before, "after": after}
    return real_divs, contaminated, len(real_divs) > 0


def _extract_df_item(form: list) -> dict | None:
    """Extract a single df (diff head) form into a viz item.

    (df name replace with value_a value_b divergences)
    """
    f = form[1:]
    if len(f) < 6:
        return None
    name = str(f[0])
    replace = str(f[1])
    with_ = str(f[2])
    value_a = _fmt_wff(f[3])
    value_b = _fmt_wff(f[4])
    divergences = f[5] if isinstance(f[5], dict) else {}
    real_divs, contaminated, has_real = split_divergences(divergences)
    coherent = value_a == value_b and not has_real
    display = f"{value_a} = {value_b}" if coherent else f"{value_a} \u2260 {value_b}"
    module = name.split(".")[0] if "." in name else ""
    return {
        "id": name,
        "kind": "diff",
        "value": display,
        "depth": 0,
        "module": module,
        "inputs": [replace, with_],
        "diff": {
            "replace": replace,
            "with": with_,
            "value_a": str(value_a),
            "value_b": str(value_b),
            "coherent": coherent,
            "divergences": real_divs,
            "contaminated": contaminated,
        },
    }


def _extract_hn_items(forms: list[list]) -> list[dict]:
    """Extract hn items from new hologram forms.

    New form: (hn <biased_lens0_ln> <biased_lens1_ln> ...)
    Each lens slot is [ln, name, kind, value, depth, inputs, ev] or [].
    """
    items = []
    for form in forms:
        f = form[1:]
        if _base_tag(form) == "hn-fmt" and len(f) >= 2:
            f = f[1:]
        if not f:
            continue
        # Each element in f is a biased lens ln form or []
        lens_data: list[dict[str, object] | None] = []
        name = ""
        kind = ""
        value = ""
        for slot in f:
            if isinstance(slot, (list, tuple)) and len(slot) >= 3 and _base_tag(slot) == "ln":
                ln = slot[1:]
                ln_name = str(ln[0]) if ln else ""
                ln_kind = str(ln[1]) if len(ln) > 1 else ""
                ln_value = str(ln[2]) if len(ln) > 2 else ""
                ln_depth = int(ln[3]) if len(ln) > 3 and isinstance(ln[3], (int, float)) else 0
                ln_inputs = [str(x) for x in ln[4]] if len(ln) > 4 and isinstance(ln[4], list) else []
                lens_data.append(
                    {
                        "name": ln_name,
                        "kind": ln_kind,
                        "value": ln_value,
                        "depth": ln_depth,
                        "inputs": ln_inputs,
                    }
                )
                if not name:
                    name = ln_name
                    kind = ln_kind
                    value = ln_value
            else:
                lens_data.append(None)  # absent from this lens
        if not name:
            continue
        module = name.split(".")[0] if "." in name else ""
        depth = next((ld["depth"] for ld in lens_data if ld is not None), 0)
        items.append(
            {
                "id": name,
                "kind": kind,
                "value": value,
                "depth": depth,
                "lenses": lens_data,
                "module": module,
            }
        )
    return items


def _ln_title(form: list) -> str:
    f = form[1:]
    if _base_tag(form) == "ln-fmt" and len(f) >= 2:
        f = f[1:]
    return str(f[0]) if f else "node"


# ── Stacked-pills layout (from CoreToConsequenceStructure) ──


def _build_layers_data(structure: CoreToConsequenceStructure, item_names: set[str] | None = None) -> dict:  # noqa: C901
    """Build stacked-pills layout data from a CoreToConsequenceStructure.

    Returns JSON-serializable dict with:
      layers: [{depth, nodes: [{name, kind, value, uses, declares, pulls, module}]}]
      edges: [{source, target, type}]  — type: use/declare/pull
    """
    from parseltongue.core.atoms import Symbol as _Sym
    from parseltongue.core.grammar import ParseltongueGrammar

    if structure is None:
        return {"layers": [], "edges": []}

    _enc = ParseltongueGrammar.enc

    def _keep(name):
        return item_names is None or name in item_names

    # Build layers from structure
    layers = []
    edges = []

    for ly in structure.layers:
        nodes = []
        for c in ly.consumers:
            if c.name.startswith("__") or not _keep(c.name):
                continue
            val_s = _enc(c.value) if c.value else ""
            node = {
                "name": c.name,
                "kind": str(c.kind),
                "value": val_s,
                "uses": [u.name for u in c.uses],
                "declares": [d_.name for d_ in c.declares],
                "pulls": [p.name for p in c.pulls],
                "module": c.name.split(".")[0] if "." in c.name else "",
            }
            nodes.append(node)

            # Edges — uses, declares, pulls + any uncovered inputs as declares
            covered = {u.name for u in c.uses} | {d_.name for d_ in c.declares} | {p.name for p in c.pulls}
            for u in c.uses:
                edges.append({"source": u.name, "target": c.name, "type": "use"})
            for d_ in c.declares:
                edges.append({"source": d_.name, "target": c.name, "type": "declare"})
            for p in c.pulls:
                edges.append({"source": p.name, "target": c.name, "type": "pull"})
            # Inputs from graph not classified by probe — treat as declares
            graph_node = structure.graph.get(c.name)
            if graph_node:
                for inp_name in graph_node.inputs:
                    if inp_name not in covered and _keep(inp_name):
                        node["declares"].append(inp_name)
                        edges.append({"source": inp_name, "target": c.name, "type": "declare"})

        if nodes:
            layers.append({"depth": ly.depth, "nodes": nodes})

    # Add missing nodes at their probe depth from structure.depths
    placed_names = {n["name"] for lay in layers for n in lay["nodes"]}
    if item_names is not None:
        missing = item_names - placed_names
        for name in sorted(missing):
            if name.startswith("__"):
                continue
            gn = structure.graph.get(name)
            if gn is None:
                continue
            d = structure.depths.get(name, 0)
            declares = [inp for inp in gn.inputs if _keep(inp)]
            node = {
                "name": name,
                "kind": str(gn.kind) if hasattr(gn, "kind") else "",
                "value": "",
                "uses": [],
                "declares": declares,
                "pulls": [],
                "module": name.split(".")[0] if "." in name else "",
            }
            existing = next((ly for ly in layers if ly["depth"] == d), None)
            if existing:
                existing["nodes"].append(node)
            else:
                layers.append({"depth": d, "nodes": [node]})
            for inp_name in declares:
                edges.append({"source": inp_name, "target": name, "type": "declare"})
        layers.sort(key=lambda ly: ly["depth"])

    # Axiom → term-fwd edges: axioms reference terms in their WFF
    from parseltongue.core.inspect.probe_core_to_consequence import NodeKind

    kept_names = {n["name"] for lay in layers for n in lay["nodes"]}

    def _syms(expr):
        if isinstance(expr, _Sym):
            return {str(expr)}
        if isinstance(expr, list):
            r = set()
            for item in expr:
                r |= _syms(item)
            return r
        return set()

    for name, graph_node in structure.graph.items():
        if graph_node.kind != NodeKind.AXIOM or graph_node.atom is None:
            continue
        if name not in kept_names:
            continue
        atom = graph_node.atom
        if not hasattr(atom, "wff"):
            continue
        for ref in _syms(atom.wff):
            if ref in kept_names and ref != name:
                ref_node = structure.graph.get(ref)
                if ref_node and ref_node.kind == NodeKind.TERM_FWD:
                    edges.append({"source": name, "target": ref, "type": "axiom-ref"})

    return {"layers": layers, "edges": edges}


# ── Render ──


def _enrich_items_from_structure(items: list[dict], structure) -> None:
    """Add definition, evidence, values, and external stubs from structure.

    Delegates to items.enrich_items — single source of truth.
    """
    from .items import enrich_items

    enrich_items(items, structure)


def _strip_internal(structure):
    """Remove __-prefixed nodes from structure so localization doesn't traverse them."""
    from parseltongue.core.inspect.probe_core_to_consequence import (
        CoreToConsequenceStructure,
        Layer,
    )

    new_layers = []
    for ly in structure.layers:
        filtered = [c for c in ly.consumers if not c.name.startswith("__")]
        new_layers.append(Layer(depth=ly.depth, consumers=filtered))
    new_graph = {n: node for n, node in structure.graph.items() if not n.startswith("__")}
    new_depths = {n: d for n, d in structure.depths.items() if not n.startswith("__")}
    return CoreToConsequenceStructure(
        layers=new_layers,
        graph=new_graph,
        depths=new_depths,
        max_depth=structure.max_depth,
    )


def _localize_multi(structure, seeds: set[str]):
    """Localize structure around seed names by filtering layers.

    Walks layers (not graph) to determine included set:
    1. Start with seeds
    2. For each consumer in layers, keep it if it IS a seed or any of its
       uses/declares/pulls touch an already-included name
    3. Repeat until stable (fixed point)
    All kept consumers preserve their original uses/declares/pulls filtered
    to the included set.
    """
    from parseltongue.core.inspect.probe_core_to_consequence import (
        Consumer,
        CoreToConsequenceStructure,
        Layer,
        NodeKind,
    )

    # Same algorithm as CoreToConsequenceStructure.localize() but multi-seed.
    # Index consumers and reverse references
    pulled_by: dict[str, set[str]] = {}
    consumer_by_name: dict[str, Consumer] = {}
    for layer in structure.layers:
        for c in layer.consumers:
            consumer_by_name[c.name] = c
            for p in c.pulls:
                pulled_by.setdefault(p.name, set()).add(c.name)

    # Axiom → term-fwd index
    from parseltongue.core.atoms import Symbol as _Sym

    def _syms(expr):
        if isinstance(expr, _Sym):
            return {str(expr)}
        if isinstance(expr, list):
            r = set()
            for item in expr:
                r |= _syms(item)
            return r
        return set()

    axiom_for_term: dict[str, list[str]] = {}
    for n, node in structure.graph.items():
        if node.kind == NodeKind.AXIOM and node.atom is not None:
            for ref in _syms(node.atom.wff):
                if ref in structure.graph and structure.graph[ref].kind == NodeKind.TERM_FWD:
                    axiom_for_term.setdefault(ref, []).append(n)

    # Phase 1: backward from seeds — full upstream via consumer inputs
    upstream = set(seeds) & set(structure.graph)
    back_queue = list(upstream)
    while back_queue:
        current = back_queue.pop()
        c = consumer_by_name.get(current)
        if c:
            for inp in c.uses + c.declares + c.pulls:
                if inp.name not in upstream:
                    upstream.add(inp.name)
                    back_queue.append(inp.name)
        for ax in axiom_for_term.get(current, []):
            if ax not in upstream:
                upstream.add(ax)
                back_queue.append(ax)

    # Phase 2: forward from seeds — follow pulls only
    forward = set()
    fwd_queue = list(seeds & set(structure.graph))
    while fwd_queue:
        current = fwd_queue.pop()
        for dependent in pulled_by.get(current, set()):
            if dependent not in forward:
                forward.add(dependent)
                fwd_queue.append(dependent)

    included = upstream | forward

    # Build layers — same as localize(): forward-only keep declares, filter pulls/uses
    new_layers = []
    for layer in structure.layers:
        filtered = []
        for c in layer.consumers:
            if c.name not in included:
                continue
            if c.name in forward and c.name not in upstream:
                trimmed = Consumer(
                    node=c.node,
                    uses=[u for u in c.uses if u.name in included],
                    declares=c.declares,
                    pulls=[p for p in c.pulls if p.name in included],
                )
                filtered.append(trimmed)
            else:
                filtered.append(c)
        new_layers.append(Layer(depth=layer.depth, consumers=filtered))

    # Collect all names referenced by included consumers (for graph/depths)
    all_names: set[str] = set()
    for layer in new_layers:
        for c in layer.consumers:
            all_names.add(c.name)
            for inp in c.uses + c.declares + c.pulls:
                all_names.add(inp.name)

    new_graph = {n: node for n, node in structure.graph.items() if n in all_names}
    new_depths = {n: d for n, d in structure.depths.items() if n in all_names}
    new_max = max(new_depths.values()) if new_depths else 0

    return CoreToConsequenceStructure(
        layers=new_layers,
        graph=new_graph,
        depths=new_depths,
        max_depth=new_max,
    )


def _build_named_structure_data(names: set[str], structure) -> list[dict]:
    """Build ln-like structure items for a set of node names found in structure.

    Delegates to items.items_from_structure — single source of truth.
    """
    from .items import items_from_structure

    if structure is None:
        return []
    return items_from_structure(structure, names=names)


def _build_sr_structure_data(sr_items: list[dict], structure) -> list[dict]:
    """Build ln-like structure items from callers found in sr results."""
    if structure is None:
        return []

    # Collect all unique caller names
    caller_names: set[str] = set()
    for item in sr_items:
        for c in item.get("callers", []):
            name = c["name"] if isinstance(c, dict) else str(c)
            caller_names.add(name)

    if not caller_names:
        return []

    return _build_named_structure_data(caller_names, structure)


def _render_app(
    items: list[dict],
    form_type: str,
    title: str,
    structure: "Any | None" = None,
    logbook: list[dict] | None = None,
    diff_structure: "Any | None" = None,
) -> str:
    structure_items = items  # default: structure tab shows same data
    layers_data: dict[str, list] = {"layers": [], "edges": []}

    if form_type == "ln" and items and structure is not None:
        item_names = {item["id"] for item in items}
        local = _localize_multi(_strip_internal(structure), item_names)
        layers_data = _build_layers_data(local)
        _enrich_items_from_structure(items, structure)
        structure_items = items
    elif form_type == "sr" and structure is not None:
        structure_items = _build_sr_structure_data(items, structure)
        if structure_items:
            seed_names = {item["id"] for item in structure_items}
            local = _localize_multi(_strip_internal(structure), seed_names)
            layers_data = _build_layers_data(local)
            # Rebuild structure_items from localized graph (includes dependencies)
            structure_items = _build_named_structure_data(set(local.graph), local)
            _enrich_items_from_structure(structure_items, structure)
    elif form_type == "dx" and items and structure is not None:
        item_names = {item.get("id", "") for item in items} - {""}
        graph = getattr(structure, "graph", {})
        found = item_names & set(graph)
        if found:
            local = _localize_multi(_strip_internal(structure), found)
            layers_data = _build_layers_data(local)
            structure_items = _build_named_structure_data(set(local.graph), local)
            _enrich_items_from_structure(structure_items, structure)
    elif form_type == "hn" and items and structure is not None:
        # Collect names per lens, localize each separately, merge
        graph = getattr(structure, "graph", {})
        n_lenses = max((len(item.get("lenses", [])) for item in items), default=0)
        merged_graph = {}
        merged_depths = {}
        merged_layers_by_depth: dict[int, list] = {}
        merged_edges = []
        for li in range(n_lenses):
            lens_names = set()
            for item in items:
                lenses = item.get("lenses", [])
                if li < len(lenses) and lenses[li] is not None:
                    lens_names.add(lenses[li]["name"])
            found = lens_names & set(graph)
            if not found:
                continue
            local = _localize_multi(_strip_internal(structure), found)
            ld = _build_layers_data(local)
            # Merge graph, depths
            merged_graph.update(local.graph)
            merged_depths.update(local.depths)
            # Merge layers
            for ly in ld["layers"]:
                existing = merged_layers_by_depth.setdefault(ly["depth"], [])
                seen = {n["name"] for n in existing}
                for n in ly["nodes"]:
                    if n["name"] not in seen:
                        existing.append(n)
                        seen.add(n["name"])
            # Merge edges (dedup)
            merged_edges.extend(ld["edges"])
        # Dedup edges
        seen_edges: set[str] = set()
        unique_edges = []
        for e in merged_edges:
            key = f"{e['source']}>{e['target']}>{e['type']}"
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(e)
        # Inject df (diff head) items into layers and edges
        for item in items:
            if item.get("kind") != "diff" or "diff" not in item:
                continue
            diff_name = item["id"]
            diff_inputs = item.get("inputs", [])
            max_d = max(merged_depths.values()) if merged_depths else -1
            diff_depth = max_d + 1
            merged_depths[diff_name] = diff_depth
            layer_nodes = merged_layers_by_depth.setdefault(diff_depth, [])
            layer_nodes.append({"name": diff_name, "kind": "diff"})
            for inp in diff_inputs:
                unique_edges.append({"source": inp, "target": diff_name, "type": "diff"})

        layers_data = {
            "layers": [{"depth": d, "nodes": ns} for d, ns in sorted(merged_layers_by_depth.items())],
            "edges": unique_edges,
        }
        structure_items = _build_named_structure_data(set(merged_graph), structure)
        # Add df items to structure_items so they appear in layers/graph
        for item in items:
            if item.get("kind") != "diff" or "diff" not in item:
                continue
            structure_items.append(item)
        _enrich_items_from_structure(structure_items, structure)

    # Merge diff possibilities if provided
    if diff_structure is not None:
        from .notebook_renderer import merge_diff_structure

        node_index = {it["id"]: it for it in structure_items}
        merge_diff_structure(structure_items, layers_data, node_index, diff_structure)

    # Compute taints from structure data + edges
    from .taints import compute_taints

    taint_result = compute_taints(
        items=structure_items,
        edges=layers_data.get("edges", []),
        structure_items=structure_items,
        logbook=logbook,
    )

    from parseltongue.core.theme import VIZ_TYPOGRAPHY, css_variables

    tmpl = Template(_read_template("app.html"))
    return tmpl.safe_substitute(
        palette_css=css_variables(include_viz=True),
        base_css=VIZ_TYPOGRAPHY,
        title=_html_escape(title),
        data_json=json.dumps(items, separators=(",", ":")),
        structure_json=json.dumps(structure_items, separators=(",", ":")),
        layers_json=json.dumps(layers_data, separators=(",", ":")),
        taint_json=json.dumps(taint_result.to_json(), separators=(",", ":")),
        form_type=form_type,
        item_count=str(len(items)),
        core_js=_read_template("core.js"),
        source_js=_read_template("source.js"),
        cards_js=_read_template("cards.js"),
        detail_js=_read_template("detail.js"),
        graph_js=_read_template("graph.js"),
        layers_js=_read_template("layers.js"),
    )
