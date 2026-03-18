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
from typing import TYPE_CHECKING, Any

from ..form_renderer import FormRenderer, _to_sexp

if TYPE_CHECKING:
    from ..store import Store


class VizRenderer(FormRenderer):
    """Tailwind + D3 renderer for bench forms."""

    def __init__(self, store: "Store | None" = None, merkle_root: str = "", structure: "Any | None" = None):
        self._store = store
        self._merkle_root = merkle_root
        self._structure = structure  # CoreToConsequenceStructure for rail layout

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

    def render_form(self, form: list) -> str:
        tag = _base_tag(form)
        if tag in ("ln", "ln-fmt"):
            return _render_app(_extract_ln_items([form]), "ln", _ln_title(form), self._structure)
        if tag in ("sr", "sr-fmt"):
            return _render_app(_extract_sr_items([form]), "sr", "Search result")
        if tag in ("dx", "dx-fmt"):
            return _render_app(_extract_dx_items([form]), "dx", "Diagnostic")
        if tag in ("hn", "hn-fmt"):
            return _render_app(_extract_hn_items([form]), "hn", "Hologram")
        return self.fmt_value(form)

    def render_form_list(self, forms: list[list]) -> str:
        if not forms:
            return self.fmt_value([])
        tag = _base_tag(forms[0])
        n = len(forms)
        if tag in ("ln", "ln-fmt"):
            return _render_app(_extract_ln_items(forms), "ln", f"{n} nodes", self._structure)
        if tag in ("sr", "sr-fmt"):
            return _render_app(_extract_sr_items(forms), "sr", f"{n} results")
        if tag in ("dx", "dx-fmt"):
            return _render_app(_extract_dx_items(forms), "dx", f"{n} diagnostics")
        if tag in ("hn", "hn-fmt"):
            return _render_app(_extract_hn_items(forms), "hn", f"{n} holograms")
        return self.fmt_value(forms)

    def fmt_value(self, val: Any) -> str:
        sexp = _to_sexp(val)
        return _HIGHLIGHT_TEMPLATE.format(content=_html_escape(sexp))


# ── Helpers ──


def _base_tag(form: list) -> str:
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
        ctx = str(f[2]) if len(f) > 2 else ""
        callers = str(f[3]) if len(f) > 3 else ""
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


def _extract_hn_items(forms: list[list]) -> list[dict]:
    items = []
    for form in forms:
        f = form[1:]
        if _base_tag(form) == "hn-fmt" and len(f) >= 2:
            f = f[1:]
        if not f:
            continue
        name = str(f[0])
        kind = str(f[1]) if len(f) > 1 else ""
        value = str(f[2]) if len(f) > 2 else ""
        lenses = [str(x) for x in f[3]] if len(f) > 3 and isinstance(f[3], list) else []
        items.append({"id": name, "kind": kind, "value": value, "lenses": lenses, "module": name.split(".")[0]})
    return items


def _ln_title(form: list) -> str:
    f = form[1:]
    if _base_tag(form) == "ln-fmt" and len(f) >= 2:
        f = f[1:]
    return str(f[0]) if f else "node"


# ── Stacked-pills layout (from CoreToConsequenceStructure) ──


def _build_layers_data(structure, item_names: set[str] | None = None) -> dict:
    """Build stacked-pills layout data from a CoreToConsequenceStructure.

    Returns JSON-serializable dict with:
      layers: [{depth, nodes: [{name, kind, value, uses, declares, pulls, module}]}]
      edges: [{source, target, type}]  — type: use/declare/pull
    """
    from parseltongue.core.atoms import Symbol as _Sym
    from parseltongue.core.lang import to_sexp as _to_sexp_val

    if structure is None:
        return {"layers": [], "edges": []}

    def _fmt_val(v):
        if v is None:
            return ""
        if isinstance(v, (list, _Sym)):
            return _to_sexp_val(v)
        return repr(v)

    def _keep(name):
        return item_names is None or name in item_names

    # Build layers from structure
    layers = []
    edges = []

    for ly in structure.layers:
        nodes = []
        for c in ly.consumers:
            if not _keep(c.name):
                continue
            val_s = _fmt_val(c.value) if c.value else ""
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

    for name, node in structure.graph.items():
        if node.kind != NodeKind.AXIOM or node.atom is None:
            continue
        if name not in kept_names:
            continue
        for ref in _syms(node.atom.wff):
            if ref in kept_names and ref != name:
                ref_node = structure.graph.get(ref)
                if ref_node and ref_node.kind == NodeKind.TERM_FWD:
                    edges.append({"source": name, "target": ref, "type": "axiom-ref"})

    return {"layers": layers, "edges": edges}


# ── Render ──


def _enrich_items_from_structure(items: list[dict], structure) -> None:
    """Add definition and rich evidence (with quotes) to DATA items from structure atoms."""
    from parseltongue.core.atoms import Axiom, Evidence, Term, Theorem
    from parseltongue.core.lang import ParseltongueGrammar

    if structure is None:
        return
    graph = getattr(structure, "graph", {})
    for item in items:
        name = item.get("id", "")
        node = graph.get(name)
        if node is None or node.atom is None:
            continue
        atom = node.atom
        # Definition (WFF string)
        if isinstance(atom, Term) and atom.definition is not None:
            item["definition"] = ParseltongueGrammar.enc(atom.definition)
        elif isinstance(atom, (Axiom, Theorem)) and atom.wff is not None:
            item["definition"] = ParseltongueGrammar.enc(atom.wff)
        # Origin status and evidence
        origin = getattr(atom, "origin", None)
        if isinstance(origin, Evidence):
            item["evidence"] = [
                {
                    "doc": origin.document,
                    "quotes": origin.quotes,
                    "explanation": origin.explanation,
                    "verified": origin.is_grounded,
                    "status": "verified" if origin.is_grounded else "unverified",
                }
            ]
        elif isinstance(atom, Theorem) or origin == "derived":
            item["evidence"] = [{"status": "derived"}]
        elif isinstance(origin, str) and origin:
            item["evidence"] = [{"doc": origin, "status": "manual"}]

    # Enrich inputs with in-probe status + create stubs for external graph nodes
    all_ids = {item.get("id", "") for item in items}
    external_needed = set()
    for item in items:
        for inp in item.get("inputs", []):
            if inp not in all_ids:
                external_needed.add(inp)

    # Build stub items for external nodes found in structure graph
    external_items = []
    for ext_name in external_needed:
        ext_node = graph.get(ext_name)
        if ext_node is None:
            continue
        ext_item = {
            "id": ext_name,
            "kind": str(ext_node.kind),
            "value": "",
            "depth": 0,
            "inputs": [{"name": i, "inProbe": i in all_ids or i in external_needed} for i in ext_node.inputs],
            "evidence": [],
            "module": ext_name.split(".")[0] if "." in ext_name else "",
            "external": True,
        }
        # Definition
        atom = ext_node.atom
        if atom is not None:
            if isinstance(atom, Term) and atom.definition is not None:
                ext_item["definition"] = ParseltongueGrammar.enc(atom.definition)
            elif isinstance(atom, (Axiom, Theorem)) and atom.wff is not None:
                ext_item["definition"] = ParseltongueGrammar.enc(atom.wff)
            origin = getattr(atom, "origin", None)
            if isinstance(origin, Evidence):
                ext_item["evidence"] = [
                    {
                        "doc": origin.document,
                        "quotes": origin.quotes,
                        "explanation": origin.explanation,
                        "verified": origin.is_grounded,
                        "status": "verified" if origin.is_grounded else "unverified",
                    }
                ]
            elif isinstance(atom, Theorem) or origin == "derived":
                ext_item["evidence"] = [{"status": "derived"}]
            elif isinstance(origin, str) and origin:
                ext_item["evidence"] = [{"doc": origin, "status": "manual"}]
        external_items.append(ext_item)
        all_ids.add(ext_name)
    items.extend(external_items)

    # Tag inputs with in-probe status
    for item in items:
        raw_inputs = item.get("inputs", [])
        if raw_inputs and raw_inputs and isinstance(raw_inputs[0], str):
            item["inputs"] = [{"name": inp, "inProbe": inp in all_ids} for inp in raw_inputs]


def _render_app(items: list[dict], form_type: str, title: str, structure: "Any | None" = None) -> str:
    if form_type == "ln" and items and structure is not None:
        item_names = {item["id"] for item in items}
        layers_data = _build_layers_data(structure, item_names)
        _enrich_items_from_structure(items, structure)
    else:
        layers_data = {"layers": [], "edges": []}
    return _APP_TEMPLATE.format(
        title=_html_escape(title),
        data_json=json.dumps(items, separators=(",", ":")),
        layers_json=json.dumps(layers_data, separators=(",", ":")),
        form_type=form_type,
        item_count=len(items),
    )


# ── Templates ──

_HIGHLIGHT_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config={{theme:{{extend:{{colors:{{base:'#1e1e2e',surface:'#313244',overlay:'#585b70',text:'#cdd6f4',subtext:'#a6adc8',green:'#a6e3a1',red:'#f38ba8',yellow:'#f9e2af',blue:'#89b4fa',mauve:'#cba6f7',teal:'#94e2d5',peach:'#fab387'}}}}}}}}</script>
</head>
<body class="bg-base text-text font-mono p-5">
<pre class="bg-surface border border-overlay rounded-lg p-4 overflow-x-auto text-sm leading-relaxed">{content}</pre>
</body>
</html>
"""

_APP_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Parseltongue — {title}</title>
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config={{theme:{{extend:{{colors:{{base:'#1e1e2e',mantle:'#181825',crust:'#11111b',surface0:'#313244',surface1:'#45475a',surface2:'#585b70',overlay0:'#6c7086',text:'#cdd6f4',subtext:'#a6adc8',green:'#a6e3a1',red:'#f38ba8',yellow:'#f9e2af',blue:'#89b4fa',mauve:'#cba6f7',teal:'#94e2d5',peach:'#fab387',flamingo:'#f2cdcd',sky:'#89dceb',lavender:'#b4befe'}}}}}}}}</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
</head>
<body class="bg-base text-text font-mono m-0 min-h-screen">

<div id="app">
  <!-- Header -->
  <div class="sticky top-0 z-20 bg-mantle/95 backdrop-blur border-b border-surface1 px-4 py-3">
    <div class="flex items-center gap-4 flex-wrap">
      <h1 class="text-lg font-bold text-lavender shrink-0">&#x1f40d; {title}</h1>
      <div class="flex-1 min-w-[200px] max-w-md">
        <input id="search" type="text" placeholder="Search names, values, modules..."
          class="w-full bg-surface0 border border-surface2 rounded-lg px-3 py-1.5 text-sm text-text placeholder-overlay0 focus:outline-none focus:border-mauve">
      </div>
      <div id="kind-filters" class="flex gap-1.5 flex-wrap"></div>
      <div class="flex gap-1.5 shrink-0">
        <button id="btn-cards" class="px-3 py-1 rounded-lg text-xs bg-mauve text-crust font-bold">Cards</button>
        <button id="btn-layers" class="px-3 py-1 rounded-lg text-xs bg-surface0 text-subtext hover:bg-surface1">Layers</button>
        <button id="btn-graph" class="px-3 py-1 rounded-lg text-xs bg-surface0 text-subtext hover:bg-surface1">Graph</button>
      </div>
      <span id="count" class="text-xs text-overlay0 shrink-0"></span>
    </div>
  </div>

  <!-- Cards View -->
  <div id="cards-view" class="p-4">
    <div id="modules-container"></div>
  </div>

  <!-- Layers View -->
  <div id="layers-view" class="hidden" style="height:calc(100vh - 60px); position:relative">
    <svg id="layers-svg" class="w-full h-full"></svg>
    <div id="layers-tooltip" class="fixed bg-surface0 border border-surface2 rounded-lg px-3 py-2 text-xs pointer-events-none max-w-sm whitespace-pre-wrap hidden z-30"></div>
    <!-- Controls overlay, top-left -->
    <div id="layers-controls" class="absolute top-3 left-3 flex gap-2 z-20">
      <button id="btn-focus-mode" class="px-3 py-1 rounded-lg text-xs bg-surface0 text-subtext border border-surface2 hover:bg-surface1">Focus mode</button>
      <button id="btn-unfocus" class="px-3 py-1 rounded-lg text-xs bg-surface0 text-subtext border border-surface2 hover:bg-surface1 hidden">Show all</button>
      <button id="btn-taints" class="px-3 py-1 rounded-lg text-xs bg-surface0 text-subtext border border-surface2 hover:bg-surface1">Taints</button>
    </div>
    <!-- Layer info overlay, bottom-left -->
    <div id="layer-info" class="fixed bottom-4 left-4 bg-mantle/95 backdrop-blur border border-surface1 rounded-lg p-3 text-xs z-20 max-w-xs hidden">
    </div>
  </div>

  <!-- Graph View -->
  <div id="graph-view" class="hidden" style="height:calc(100vh - 60px)">
    <svg id="graph" class="w-full h-full"></svg>
    <div id="tooltip" class="fixed bg-surface0 border border-surface2 rounded-lg px-3 py-2 text-xs pointer-events-none max-w-sm whitespace-pre-wrap hidden z-30"></div>
  </div>

  <!-- Detail Panel -->
  <div id="detail-panel" class="fixed top-0 right-0 h-full w-[420px] bg-mantle border-l border-surface1 z-30 transform translate-x-full transition-transform duration-200 overflow-y-auto">
    <div class="sticky top-0 bg-mantle/95 backdrop-blur border-b border-surface1 px-4 py-3 flex items-center justify-between">
      <h2 id="detail-title" class="text-sm font-bold text-lavender truncate"></h2>
      <button id="detail-close" class="text-overlay0 hover:text-text text-lg leading-none">&times;</button>
    </div>
    <div id="detail-body" class="p-4 text-sm space-y-4"></div>
  </div>
</div>

<script>
const DATA = {data_json};
const LAYERS = {layers_json};
const FORM_TYPE = "{form_type}";
const KIND_COLORS = {{
  fact:'bg-green',axiom:'bg-peach',defterm:'bg-blue',theorem:'bg-mauve',
  diff:'bg-red',derive:'bg-mauve',evidence:'bg-overlay0','search-result':'bg-green',
  diagnostic:'bg-red',hologram:'bg-teal',document:'bg-sky',input:'bg-surface2',
  lens:'bg-lavender',unknown:'bg-surface2'
}};
const KIND_TEXT = {{
  fact:'text-green',axiom:'text-peach',defterm:'text-blue',theorem:'text-mauve',
  diff:'text-red',derive:'text-mauve',evidence:'text-overlay0','search-result':'text-green',
  diagnostic:'text-red',hologram:'text-teal',document:'text-sky',lens:'text-lavender'
}};
const KIND_DOT = {{
  fact:'#a6e3a1',axiom:'#fab387',defterm:'#89b4fa',theorem:'#cba6f7',
  diff:'#f38ba8',derive:'#cba6f7',evidence:'#6c7086','search-result':'#a6e3a1',
  diagnostic:'#f38ba8',hologram:'#94e2d5',document:'#89dceb',input:'#585b70',
  lens:'#b4befe'
}};

function kindColor(k) {{ return KIND_COLORS[k] || KIND_COLORS.unknown; }}
function kindText(k) {{ return KIND_TEXT[k] || 'text-subtext'; }}
function kindDot(k) {{ return KIND_DOT[k] || '#585b70'; }}
function esc(s) {{ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}

// ── State ──
let activeKinds = new Set();
let searchQuery = '';
let currentView = 'cards';

// ── Kind discovery ──
const allKinds = [...new Set(DATA.map(d => d.kind || d.category || ''))].filter(Boolean).sort();

// ── Filters ──
const filtersEl = document.getElementById('kind-filters');
allKinds.forEach(k => {{
  const btn = document.createElement('button');
  btn.className = `px-2 py-0.5 rounded text-xs border border-surface2 ${{kindText(k)}} hover:bg-surface1 transition-colors`;
  btn.textContent = k;
  btn.dataset.kind = k;
  btn.onclick = () => {{
    if (activeKinds.has(k)) {{ activeKinds.delete(k); btn.classList.remove('bg-surface1','font-bold'); btn.classList.add('bg-transparent'); }}
    else {{ activeKinds.add(k); btn.classList.add('bg-surface1','font-bold'); btn.classList.remove('bg-transparent'); }}
    render();
  }};
  filtersEl.appendChild(btn);
}});

// ── Search ──
const searchEl = document.getElementById('search');
searchEl.addEventListener('input', (e) => {{ searchQuery = e.target.value.toLowerCase(); render(); }});

// ── View toggle ──
const VIEW_BTNS = ['cards', 'layers', 'graph'];
VIEW_BTNS.forEach(v => {{
  document.getElementById('btn-' + v).onclick = () => switchView(v);
}});

function switchView(v) {{
  currentView = v;
  VIEW_BTNS.forEach(id => {{
    document.getElementById(id + '-view').classList.toggle('hidden', v !== id);
    document.getElementById('btn-' + id).className = v === id
      ? 'px-3 py-1 rounded-lg text-xs bg-mauve text-crust font-bold'
      : 'px-3 py-1 rounded-lg text-xs bg-surface0 text-subtext hover:bg-surface1';
  }});
  if (v === 'graph') renderGraph();
  if (v === 'layers') renderLayers();
}}

// ── Filter logic ──
function filtered() {{
  return DATA.filter(d => {{
    const k = d.kind || d.category || '';
    if (activeKinds.size > 0 && !activeKinds.has(k)) return false;
    if (searchQuery) {{
      const hay = JSON.stringify(d).toLowerCase();
      return hay.includes(searchQuery);
    }}
    return true;
  }});
}}

// ── Cards render ──
function render() {{
  const items = filtered();
  document.getElementById('count').textContent = `${{items.length}} / ${{DATA.length}}`;
  const container = document.getElementById('modules-container');
  container.innerHTML = '';

  // Group by module
  const groups = {{}};
  items.forEach(d => {{
    const m = d.module || '(ungrouped)';
    if (!groups[m]) groups[m] = [];
    groups[m].push(d);
  }});

  const sortedModules = Object.keys(groups).sort();
  sortedModules.forEach(mod => {{
    const section = document.createElement('div');
    section.className = 'mb-6';

    const header = document.createElement('div');
    header.className = 'flex items-center gap-2 mb-2 cursor-pointer select-none group';
    header.innerHTML = `
      <span class="text-xs text-overlay0 group-hover:text-text transition-colors">&#9660;</span>
      <span class="text-sm font-bold text-lavender">${{esc(mod)}}</span>
      <span class="text-xs text-overlay0">${{groups[mod].length}}</span>
    `;
    let collapsed = false;
    const grid = document.createElement('div');
    grid.className = 'grid gap-2 grid-cols-[repeat(auto-fill,minmax(340px,1fr))]';

    header.onclick = () => {{
      collapsed = !collapsed;
      grid.classList.toggle('hidden', collapsed);
      header.querySelector('span').textContent = collapsed ? '\\u25b6' : '\\u25bc';
    }};

    groups[mod].forEach(d => {{
      const card = document.createElement('div');
      card.className = 'bg-surface0 border border-surface1 rounded-lg p-3 hover:border-mauve/50 cursor-pointer transition-colors';
      card.onclick = () => showDetail(d);

      if (FORM_TYPE === 'ln') {{
        const name = d.id || '';
        const short = name.includes('.') ? name.split('.').slice(1).join('.') : name;
        const kind = d.kind || '';
        const val = d.value || '';
        const hasEv = d.evidence && d.evidence.length > 0;
        const verified = hasEv && d.evidence[0].verified;
        card.innerHTML = `
          <div class="flex items-start justify-between gap-2 mb-1">
            <span class="text-xs font-bold text-text truncate" title="${{esc(name)}}">${{esc(short)}}</span>
            <span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold ${{kindColor(kind)}} text-crust">${{esc(kind)}}</span>
          </div>
          ${{val ? `<div class="text-xs text-subtext truncate mb-1" title="${{esc(val)}}">${{esc(val.length > 80 ? val.slice(0,77)+'...' : val)}}</div>` : ''}}
          <div class="flex items-center gap-2 text-[10px] text-overlay0">
            ${{d.inputs && d.inputs.length ? `<span>&#x2190; ${{d.inputs.length}} inputs</span>` : ''}}
            ${{hasEv ? `<span class="${{verified ? 'text-green' : 'text-yellow'}}">${{verified ? '&#x2713; verified' : '&#x25cb; unverified'}}</span>` : ''}}
            ${{d.depth > 0 ? `<span>depth ${{d.depth}}</span>` : ''}}
          </div>
        `;
      }} else if (FORM_TYPE === 'sr') {{
        card.innerHTML = `
          <div class="flex items-center gap-2 mb-1">
            <span class="text-xs font-bold text-sky">${{esc(d.doc)}}</span>
            <span class="text-[10px] text-overlay0">:${{esc(d.line)}}</span>
          </div>
          <div class="text-xs text-subtext truncate">${{esc(d.ctx)}}</div>
          ${{d.callers ? `<div class="text-[10px] text-overlay0 mt-1">${{esc(d.callers)}}</div>` : ''}}
        `;
      }} else if (FORM_TYPE === 'dx') {{
        card.innerHTML = `
          <div class="flex items-start justify-between gap-2 mb-1">
            <span class="text-xs font-bold text-text truncate">${{esc(d.id)}}</span>
            <span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold bg-red text-crust">${{esc(d.category)}}</span>
          </div>
          ${{d.detail ? `<div class="text-xs text-subtext">${{esc(d.detail)}}</div>` : ''}}
          <div class="text-[10px] text-overlay0">${{esc(d.kind)}} / ${{esc(d.type)}}</div>
        `;
      }} else if (FORM_TYPE === 'hn') {{
        card.innerHTML = `
          <div class="flex items-start justify-between gap-2 mb-1">
            <span class="text-xs font-bold text-teal">${{esc(d.id)}}</span>
            ${{d.kind ? `<span class="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold bg-teal text-crust">${{esc(d.kind)}}</span>` : ''}}
          </div>
          ${{d.lenses && d.lenses.length ? `<div class="text-xs text-subtext">${{d.lenses.length}} lenses: ${{d.lenses.slice(0,3).map(l => esc(l)).join(', ')}}${{d.lenses.length > 3 ? '...' : ''}}</div>` : ''}}
        `;
      }}
      grid.appendChild(card);
    }});

    section.appendChild(header);
    section.appendChild(grid);
    container.appendChild(section);
  }});
}}

// ── Data index for tree walks ──
const ITEM_BY_ID = {{}};
DATA.forEach(d => {{ ITEM_BY_ID[d.id] = d; }});

// ── Derivation tree builder ──
function buildDerivationTree(rootId, maxDepth) {{
  maxDepth = maxDepth || 20;
  const visited = new Set();
  function walk(id, depth) {{
    const node = ITEM_BY_ID[id];
    const entry = {{
      id: id,
      kind: node ? node.kind : '?',
      value: node ? node.value : '',
      depth: node ? node.depth : -1,
      children: [],
      cycle: false,
      external: !node,
      outsideFocus: node ? !!node.external : !node
    }};
    if (visited.has(id) || depth >= maxDepth) {{
      entry.cycle = visited.has(id);
      return entry;
    }}
    visited.add(id);
    if (node && node.inputs) {{
      node.inputs.forEach(inp => {{
        const inpName = typeof inp === 'string' ? inp : inp.name;
        entry.children.push(walk(inpName, depth + 1));
      }});
    }}
    return entry;
  }}
  return walk(rootId, 0);
}}

function renderTree(tree) {{
  // Render as nested HTML tree with connectors
  function renderNode(node, isLast, prefix) {{
    const connector = prefix === '' ? '' : (isLast ? '&#x2514;&#x2500;&#x2500; ' : '&#x251c;&#x2500;&#x2500; ');
    const kindCls = kindText(node.kind);
    const badge = `<span class="px-1 py-0.5 rounded text-[9px] ${{kindColor(node.kind)}} text-crust">${{esc(node.kind)}}</span>`;
    const short = node.id.includes('.') ? node.id.split('.').slice(1).join('.') : node.id;
    const nameSpan = node.external
      ? `<span class="text-overlay0 italic">${{esc(short)}}</span>`
      : node.outsideFocus
        ? `<span class="text-subtext cursor-pointer hover:text-mauve" onclick="showDetail(ITEM_BY_ID['${{node.id.replace(/'/g, "\\\\'")}}'])">${{esc(short)}}</span>`
        : `<span class="text-text font-bold cursor-pointer hover:text-mauve" onclick="showDetail(ITEM_BY_ID['${{node.id.replace(/'/g, "\\\\'")}}'])">${{esc(short)}}</span>`;
    const valSnip = node.value ? `<span class="text-subtext ml-1 text-[9px]">= ${{esc(String(node.value).slice(0, 40))}}</span>` : '';
    const layerTag = node.depth >= 0 ? `<span class="text-[9px] text-overlay0 ml-1">L${{node.depth}}</span>` : '';
    const cycleTag = node.cycle ? ' <span class="text-yellow text-[9px]">&#x21bb; cycle</span>' : '';

    let html = `<div class="flex items-center gap-1 py-0.5">`;
    html += `<span class="text-surface2 whitespace-pre font-mono text-[10px]">${{prefix}}${{connector}}</span>`;
    html += `${{nameSpan}} ${{badge}}${{valSnip}}${{layerTag}}${{cycleTag}}`;
    html += `</div>`;

    if (node.children.length > 0 && !node.cycle) {{
      const childPrefix = prefix === '' ? '' : (prefix + (isLast ? '&nbsp;&nbsp;&nbsp;&nbsp;' : '&#x2502;&nbsp;&nbsp;&nbsp;'));
      node.children.forEach((child, i) => {{
        html += renderNode(child, i === node.children.length - 1, childPrefix || '');
      }});
    }}
    return html;
  }}
  return renderNode(tree, true, '');
}}

// ── Detail panel ──
const panel = document.getElementById('detail-panel');
document.getElementById('detail-close').onclick = () => panel.classList.add('translate-x-full');

function showDetail(d) {{
  if (!d) return;
  panel.classList.remove('translate-x-full');
  document.getElementById('detail-title').textContent = d.id || d.doc || '';
  const body = document.getElementById('detail-body');
  let html = '';

  if (FORM_TYPE === 'ln') {{
    html += `<div class="space-y-3">`;
    if (d.external) {{
      html += `<div class="bg-surface0 border border-surface2 rounded px-2 py-1 text-[10px] text-overlay0 mb-2">Outside current focus &mdash; data from probe graph</div>`;
    }}
    html += `<div><span class="text-overlay0">name:</span> <span class="text-text font-bold">${{esc(d.id)}}</span></div>`;
    html += `<div><span class="text-overlay0">kind:</span> <span class="${{kindText(d.kind)}} font-bold">${{esc(d.kind)}}</span></div>`;
    if (d.value) html += `<div><span class="text-overlay0">value:</span><div class="mt-1 bg-surface0 rounded p-2 text-xs whitespace-pre-wrap">${{esc(d.value)}}</div></div>`;
    if (d.depth > 0) html += `<div><span class="text-overlay0">depth:</span> ${{d.depth}}</div>`;

    // ── Definition (WFF) ──
    if (d.definition) {{
      html += `<div class="border-t border-surface2 pt-3"><span class="text-overlay0 font-bold">Definition</span>`;
      html += `<div class="mt-1 bg-crust rounded-lg p-3 text-xs whitespace-pre-wrap font-mono text-lavender">${{esc(d.definition)}}</div>`;
      html += `</div>`;
    }}

    // ── Evidence with quotes ──
    if (d.evidence && d.evidence.length) {{
      html += `<div class="border-t border-surface2 pt-3"><span class="text-overlay0 font-bold">Evidence</span>`;
      d.evidence.forEach(ev => {{
        const st = ev.status || (ev.verified ? 'verified' : 'unverified');
        if (st === 'derived') {{
          html += `<div class="mt-2 text-xs text-blue">&#x2713; derived (proven by derivation)</div>`;
          return;
        }}
        html += `<div class="mt-2 bg-crust rounded-lg p-3 space-y-1">`;
        if (ev.doc) html += `<div class="text-xs"><span class="text-overlay0">doc:</span> <span class="text-sky">${{esc(ev.doc)}}</span></div>`;
        if (ev.quotes && ev.quotes.length) {{
          ev.quotes.forEach(q => {{
            const bc = st === 'verified' ? 'border-green' : 'border-yellow';
            html += `<div class="text-xs bg-surface0 rounded p-2 mt-1 whitespace-pre-wrap border-l-2 ${{bc}}">${{esc(q)}}</div>`;
          }});
        }} else if (ev.quote) {{
          const bc = st === 'verified' ? 'border-green' : 'border-yellow';
          html += `<div class="text-xs bg-surface0 rounded p-2 mt-1 whitespace-pre-wrap border-l-2 ${{bc}}">${{esc(ev.quote)}}</div>`;
        }}
        if (ev.explanation) html += `<div class="text-xs text-subtext mt-1">${{esc(ev.explanation)}}</div>`;
        if (ev.label) html += `<div class="text-xs text-subtext mt-1">${{esc(ev.label)}}</div>`;
        const stColor = st === 'verified' ? 'text-green' : st === 'manual' ? 'text-peach' : 'text-yellow';
        const stIcon = st === 'verified' ? '&#x2713;' : st === 'manual' ? '&#x270e;' : '&#x25cb;';
        html += `<div class="text-[10px] ${{stColor}}">${{stIcon}} ${{st}}</div>`;
        html += `</div>`;
      }});
      html += `</div>`;
    }}

    // ── Derivation tree (last) ──
    if (d.inputs && d.inputs.length) {{
      const tree = buildDerivationTree(d.id, 15);
      html += `<div class="border-t border-surface2 pt-3">`;
      html += `<div class="text-overlay0 font-bold mb-2">Derivation path</div>`;
      html += `<div class="bg-crust rounded-lg p-3 text-xs overflow-x-auto">${{renderTree(tree)}}</div>`;
      html += `</div>`;
    }}
    html += `</div>`;
  }} else if (FORM_TYPE === 'sr') {{
    html += `<div class="space-y-2">`;
    html += `<div><span class="text-overlay0">document:</span> <span class="text-sky font-bold">${{esc(d.doc)}}</span></div>`;
    html += `<div><span class="text-overlay0">line:</span> ${{esc(d.line)}}</div>`;
    if (d.ctx) html += `<div class="bg-surface0 rounded p-2 text-xs whitespace-pre-wrap">${{esc(d.ctx)}}</div>`;
    if (d.callers) html += `<div><span class="text-overlay0">callers:</span> ${{esc(d.callers)}}</div>`;
    html += `</div>`;
  }} else if (FORM_TYPE === 'dx') {{
    html += `<div class="space-y-2">`;
    html += `<div><span class="text-overlay0">name:</span> <span class="font-bold">${{esc(d.id)}}</span></div>`;
    html += `<div><span class="text-overlay0">category:</span> <span class="text-red">${{esc(d.category)}}</span></div>`;
    html += `<div><span class="text-overlay0">kind:</span> ${{esc(d.kind)}}</div>`;
    html += `<div><span class="text-overlay0">type:</span> ${{esc(d.type)}}</div>`;
    if (d.detail) html += `<div class="bg-surface0 rounded p-2 text-xs whitespace-pre-wrap">${{esc(d.detail)}}</div>`;
    html += `</div>`;
  }} else if (FORM_TYPE === 'hn') {{
    html += `<div class="space-y-2">`;
    html += `<div><span class="text-overlay0">name:</span> <span class="text-teal font-bold">${{esc(d.id)}}</span></div>`;
    if (d.kind) html += `<div><span class="text-overlay0">kind:</span> ${{esc(d.kind)}}</div>`;
    if (d.value) html += `<div class="bg-surface0 rounded p-2 text-xs whitespace-pre-wrap">${{esc(d.value)}}</div>`;
    if (d.lenses && d.lenses.length) {{
      html += `<div><span class="text-overlay0">lenses (${{d.lenses.length}}):</span><div class="mt-1 flex flex-wrap gap-1">`;
      d.lenses.forEach(l => {{
        html += `<span class="px-2 py-0.5 rounded bg-surface0 text-xs text-lavender">${{esc(l)}}</span>`;
      }});
      html += `</div></div>`;
    }}
    html += `</div>`;
  }}
  body.innerHTML = html;
}}

function highlightInput(name) {{
  searchEl.value = name;
  searchQuery = name.toLowerCase();
  render();
}}

// ── D3 Graph ──
let graphInitialized = false;

function renderGraph() {{
  if (graphInitialized) return;
  graphInitialized = true;

  const items = filtered();
  const nodes = [];
  const links = [];
  const seen = new Set();

  items.forEach(d => {{
    const id = d.id || `${{d.doc}}:${{d.line}}`;
    if (seen.has(id)) return;
    seen.add(id);
    nodes.push({{ id, kind: d.kind || d.category || '', value: d.value || d.ctx || '', color: kindDot(d.kind || d.category || '') }});
    if (d.inputs) d.inputs.forEach(inp => {{
      links.push({{ source: inp, target: id }});
      if (!seen.has(inp)) {{
        seen.add(inp);
        nodes.push({{ id: inp, kind: 'input', value: '', color: kindDot('input') }});
      }}
    }});
    if (d.lenses) d.lenses.forEach(l => {{
      links.push({{ source: id, target: l }});
      if (!seen.has(l)) {{
        seen.add(l);
        nodes.push({{ id: l, kind: 'lens', value: '', color: kindDot('lens') }});
      }}
    }});
  }});

  const svg = d3.select("#graph");
  const width = window.innerWidth;
  const height = window.innerHeight - 60;
  const g = svg.append("g");
  svg.call(d3.zoom().scaleExtent([0.1, 8]).on("zoom", (e) => g.attr("transform", e.transform)));

  const sim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).id(d => d.id).distance(60))
    .force("charge", d3.forceManyBody().strength(-120))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collision", d3.forceCollide().radius(15));

  const link = g.append("g").selectAll("line")
    .data(links).join("line").attr("stroke", "#585b70").attr("stroke-opacity", 0.4);

  const node = g.append("g").selectAll("g")
    .data(nodes).join("g").attr("class", "cursor-pointer")
    .call(d3.drag()
      .on("start", (e, d) => {{ if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
      .on("drag", (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
      .on("end", (e, d) => {{ if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }}));

  node.append("circle").attr("r", 5).attr("fill", d => d.color).attr("stroke", "#313244").attr("stroke-width", 1);
  node.append("text").attr("dx", 8).attr("dy", 3).attr("fill", "#cdd6f4").attr("font-size", "9px")
    .text(d => d.id.length > 30 ? d.id.slice(0, 27) + '...' : d.id);

  const tooltip = d3.select("#tooltip");
  node.on("mouseover", (e, d) => {{
    tooltip.html(`<b>${{d.id}}</b>\\n${{d.kind}}${{d.value ? '\\n' + d.value.slice(0, 120) : ''}}`).classed("hidden", false)
      .style("left", (e.pageX + 12) + "px").style("top", (e.pageY - 8) + "px");
    link.attr("stroke", l => (l.source.id === d.id || l.target.id === d.id) ? '#f9e2af' : '#585b70')
        .attr("stroke-opacity", l => (l.source.id === d.id || l.target.id === d.id) ? 1 : 0.4)
        .attr("stroke-width", l => (l.source.id === d.id || l.target.id === d.id) ? 2 : 1);
  }}).on("mouseout", () => {{
    tooltip.classed("hidden", true);
    link.attr("stroke", "#585b70").attr("stroke-opacity", 0.4).attr("stroke-width", 1);
  }}).on("click", (e, d) => {{
    const item = DATA.find(i => (i.id || `${{i.doc}}:${{i.line}}`) === d.id);
    if (item) showDetail(item);
  }});

  sim.on("tick", () => {{
    link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
        .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
  }});
}}

// ── Layers View: stacked pills with curved connections ──
let layersInitialized = false;
let focusMode = false;
let focusedId = null;

function renderLayers() {{
  if (layersInitialized) return;
  layersInitialized = true;

  if (!LAYERS.layers.length) {{
    document.getElementById('layers-svg').outerHTML =
      '<div class="flex items-center justify-center h-full text-overlay0">Layers view requires lens (ln) data.</div>';
    return;
  }}

  const svg = d3.select("#layers-svg");
  const W = window.innerWidth;
  const H = window.innerHeight - 60;
  const g = svg.append("g");
  const zoomBehavior = d3.zoom().scaleExtent([0.02, 10]).on("zoom", (e) => g.attr("transform", e.transform));
  svg.call(zoomBehavior);

  const tooltip = d3.select("#layers-tooltip");
  const info = document.getElementById("layer-info");

  // ── Build dependency maps ──
  const parentsOf = {{}};   // name → [input names]
  const childrenOf = {{}};  // name → [consumer names]
  LAYERS.edges.forEach(e => {{
    if (!parentsOf[e.target]) parentsOf[e.target] = [];
    parentsOf[e.target].push(e.source);
    if (!childrenOf[e.source]) childrenOf[e.source] = [];
    childrenOf[e.source].push(e.target);
  }});

  function collectPath(id) {{
    const path = new Set();
    const upQ = [id];
    while (upQ.length) {{
      const n = upQ.pop();
      if (path.has(n)) continue;
      path.add(n);
      (parentsOf[n] || []).forEach(p => upQ.push(p));
    }}
    const downQ = [id];
    while (downQ.length) {{
      const n = downQ.pop();
      if (path.has(n)) continue;
      path.add(n);
      (childrenOf[n] || []).forEach(c => downQ.push(c));
    }}
    return path;
  }}

  // ── Layout: "rails but pills" — input column + result column per layer ──
  const PH = 26;           // result pill height
  const SUB_PH = 18;       // input sub-pill height
  const PW_MIN = 130;      // min result pill width
  const PW_MAX = 240;      // max result pill width
  const SPW_MIN = 80;      // min sub-pill width
  const SPW_MAX = 180;     // max sub-pill width
  const GAP_X = 50;        // gap between layers
  const GAP_XI = 12;       // gap between input col and result col
  const GAP_Y = 8;         // gap between consumer rows
  const SUB_GAP_Y = 2;     // gap between input pills in a group
  const LABEL_H = 56;      // layer label height (L title + stats widget)
  const PAD = 30;           // padding

  const pos = {{}};
  const nodeData = {{}};
  const inputPillData = {{}};

  function getConsumerInputs(n) {{
    // Uses and declares (facts) get input sub-pills. Pulls are just lines.
    const pills = [];
    (n.uses || []).forEach(u => pills.push({{id: 'inp:'+u+'>'+n.name, label: u, consumer: n.name, type: 'use'}}));
    (n.declares || []).forEach(d => pills.push({{id: 'inp:'+d+'>'+n.name, label: d, consumer: n.name, type: 'declare'}}));
    return pills;
  }}

  const TYPE_COLOR = {{'use':'#a6e3a1','declare':'#6c7086','pull':'#89b4fa','axiom-ref':'#fab387'}};
  const TYPE_STROKE = {{'use':'#a6e3a1','declare':'#585b70','pull':'#89b4fa'}};

  // ── Identify hanging nodes: L0 nodes that never reach a deeper layer ──
  // A node is hanging if no path from it leads to any node in layer > 0.
  const deepNames = new Set();
  LAYERS.layers.forEach(lay => {{ if (lay.depth > 0) lay.nodes.forEach(n => deepNames.add(n.name)); }});
  const l0Names = new Set();
  LAYERS.layers.forEach(lay => {{ if (lay.depth === 0) lay.nodes.forEach(n => l0Names.add(n.name)); }});
  // Build forward adjacency: source → [targets]
  const fwd = {{}};
  LAYERS.edges.forEach(e => {{ if (!fwd[e.source]) fwd[e.source] = []; fwd[e.source].push(e.target); }});
  // BFS from each L0 node — does it reach any deep node?
  const reachesDeep = new Set();
  l0Names.forEach(start => {{
    if (reachesDeep.has(start)) return;
    const visited = new Set();
    const q = [start];
    let found = false;
    while (q.length) {{
      const n = q.pop();
      if (visited.has(n)) continue;
      visited.add(n);
      if (deepNames.has(n)) {{ found = true; break; }}
      (fwd[n] || []).forEach(t => q.push(t));
    }}
    if (found) visited.forEach(v => {{ if (l0Names.has(v)) reachesDeep.add(v); }});
  }});
  const hangingNodes = [];

  // ── Measure and layout ──
  let curX = PAD;
  LAYERS.layers.forEach((lay, li) => {{
    // Separate hanging from connected in layer 0
    if (lay.depth === 0) {{
      const connected = [];
      lay.nodes.forEach(n => {{
        nodeData[n.name] = n;
        if (reachesDeep.has(n.name)) connected.push(n);
        else hangingNodes.push(n);
      }});
      lay.nodes = connected;
      if (!connected.length) return;
    }} else {{
      lay.nodes.forEach(n => {{ nodeData[n.name] = n; }});
    }}

    // Collect input pills — deduped by source name within layer (uses + declares)
    const useSeen = {{}};
    const layerInputs = [];
    lay.nodes.forEach(n => {{
      (n.uses || []).forEach(u => {{
        if (!useSeen[u]) {{
          useSeen[u] = {{id: 'inp:'+u+'@'+li, label: u, consumers: [], type: 'use'}};
          layerInputs.push(useSeen[u]);
        }}
        useSeen[u].consumers.push(n.name);
      }});
      (n.declares || []).forEach(d => {{
        if (!useSeen[d]) {{
          useSeen[d] = {{id: 'inp:'+d+'@'+li, label: d, consumers: [], type: 'declare'}};
          layerInputs.push(useSeen[d]);
        }}
        useSeen[d].consumers.push(n.name);
      }});
    }});
    layerInputs.forEach(p => {{ inputPillData[p.id] = p; }});
    const hasInputs = layerInputs.length > 0;

    // Measure input column width
    let inputColW = 0;
    if (hasInputs) {{
      layerInputs.forEach(inp => {{
        const short = inp.label.includes('.') ? inp.label.split('.').slice(1).join('.') : inp.label;
        inp._w = Math.min(SPW_MAX, Math.max(SPW_MIN, short.length * 5.5 + 20));
        inputColW = Math.max(inputColW, inp._w);
      }});
    }}

    // Measure result column width
    let resultColW = 0;
    lay.nodes.forEach(n => {{
      const short = n.name.includes('.') ? n.name.split('.').slice(1).join('.') : n.name;
      const label = short + (n.value ? ' =' + String(n.value).slice(0,15) : '');
      n._w = Math.min(PW_MAX, Math.max(PW_MIN, label.length * 6.5 + 28));
      resultColW = Math.max(resultColW, n._w);
    }});

    const inputX = curX;
    const resultX = hasInputs ? curX + inputColW + GAP_XI : curX;
    lay._labelX = curX;
    lay._colW = resultX + resultColW - curX;
    lay._inputX = inputX;
    lay._inputColW = inputColW;
    lay._hasInputs = hasInputs;

    // Position input pills (deduped, stacked in input column)
    let inputY = PAD + LABEL_H;
    layerInputs.forEach(inp => {{
      pos[inp.id] = {{
        x: inputX, y: inputY,
        w: inp._w, h: SUB_PH, isInput: true, type: inp.type, depth: lay.depth
      }};
      inputY += SUB_PH + SUB_GAP_Y;
    }});

    // Position result pills (stacked in result column)
    let resultY = PAD + LABEL_H;
    lay.nodes.forEach(n => {{
      pos[n.name] = {{ x: resultX, y: resultY, w: n._w, h: PH, depth: lay.depth }};
      resultY += PH + GAP_Y;
    }});
    lay._colH = Math.max(inputY, resultY);
    curX = resultX + resultColW + GAP_X;
  }});

  // ── Taint computation (needed for stats) ──
  const taintSources = new Set();
  DATA.forEach(d => {{
    const hasEv = d.evidence && d.evidence.length > 0;
    if (!hasEv) {{ taintSources.add(d.id); return; }}
    const allOk = d.evidence.every(e => e.status === 'verified' || e.status === 'derived' || e.status === 'manual');
    if (!allOk) taintSources.add(d.id);
  }});
  function computeTainted() {{
    const tainted = new Set(taintSources);
    const q = [...taintSources];
    while (q.length) {{
      const n = q.pop();
      (childrenOf[n] || []).forEach(c => {{
        if (!tainted.has(c)) {{ tainted.add(c); q.push(c); }}
      }});
    }}
    return tainted;
  }}
  const _allTainted = computeTainted();

  // ── Draw layer labels + stats widget ──
  function pct(n, t) {{ return t ? Math.round(n / t * 100) : 0; }}

  LAYERS.layers.forEach(lay => {{
    if (!lay.nodes.length) return;
    const cx = lay._labelX + lay._colW / 2;

    // Separator line
    g.append("line")
      .attr("x1", lay._labelX - 6).attr("y1", PAD)
      .attr("x2", lay._labelX - 6).attr("y2", lay._colH || PAD + 40)
      .attr("stroke", "#313244").attr("stroke-width", 1).attr("stroke-dasharray", "3,3")
      .attr("class", "layer-label");

    // "inputs" label
    if (lay._hasInputs) {{
      g.append("text")
        .attr("x", lay._inputX + lay._inputColW / 2).attr("y", PAD + LABEL_H - 4)
        .attr("text-anchor", "middle")
        .attr("fill", "#a6e3a1").attr("font-size", "8px").attr("font-style", "italic")
        .attr("class", "layer-label")
        .text("inputs");
    }}

    // ── Gather all nodes + inputs for aggregated stats ──
    const kindCounts = {{}};       // kind → {{main: N, input: M}}
    let taintedCount = 0, taintSourceCount = 0;

    lay.nodes.forEach(n => {{
      if (!kindCounts[n.kind]) kindCounts[n.kind] = {{main: 0, input: 0}};
      kindCounts[n.kind].main++;
      if (taintSources.has(n.name)) taintSourceCount++;
      if (_allTainted.has(n.name)) taintedCount++;
    }});

    const inpSeen = new Set();
    lay.nodes.forEach(n => {{
      (n.uses || []).forEach(u => {{ if (!inpSeen.has(u)) inpSeen.add(u); }});
      (n.declares || []).forEach(d => {{ if (!inpSeen.has(d)) inpSeen.add(d); }});
    }});
    let inpTainted = 0, inpUnverified = 0;
    inpSeen.forEach(name => {{
      if (_allTainted.has(name)) inpTainted++;
      if (taintSources.has(name)) inpUnverified++;
      const item = ITEM_BY_ID[name];
      const k = item ? item.kind : 'unknown';
      if (!kindCounts[k]) kindCounts[k] = {{main: 0, input: 0}};
      kindCounts[k].input++;
    }});

    const total = lay.nodes.length;
    const inputTotal = inpSeen.size;
    const allTotal = total + inputTotal;
    const allUnverified = taintSourceCount + inpUnverified;
    const allTainted = taintedCount + inpTainted;
    const allPropagated = allTainted - allUnverified;

    // Sort by total (main+input) descending
    const kindEntries = Object.entries(kindCounts).sort((a,b) => (b[1].main + b[1].input) - (a[1].main + a[1].input));
    const maxCount = kindEntries.length ? Math.max(...kindEntries.map(([,v]) => v.main + v.input)) : 1;

    // ── Stats widget: square panel, right of L label, bottom-aligned with L title ──
    const panelS = 53;           // square size
    const barChartW = panelS;
    const barH = Math.min(6, Math.max(3, (panelS - 4) / Math.max(kindEntries.length, 1) - 1));
    const panelH = Math.max(panelS, kindEntries.length * (barH + 1) + 4);
    const taintLineH = 12;
    const widgetH = panelH + taintLineH;

    // L label aligned with inputs label
    const labelY = PAD + LABEL_H - 4;
    g.append("text")
      .attr("x", cx).attr("y", labelY)
      .attr("text-anchor", "middle")
      .attr("fill", "#6c7086").attr("font-size", "10px").attr("font-weight", "bold")
      .attr("class", "layer-label")
      .text(`L${{lay.depth}} (${{lay.nodes.length}})`);

    // Widget position: right of L label, bottom-aligned with L baseline
    const widgetBottom = labelY + 2;
    const widgetTop = widgetBottom - widgetH;
    const wx = cx + 24;

    const sg = g.append("g").attr("transform", `translate(${{wx}},${{widgetTop}})`).attr("class", "layer-label");

    // Background
    const labelW = Math.max(...kindEntries.map(([k, v]) => (k + ' ' + (v.main + v.input)).length)) * 3.2 + 4;
    const totalW = barChartW + labelW + 4;
    sg.append("rect").attr("width", totalW).attr("height", widgetH).attr("rx", 4)
      .attr("fill", "#181825").attr("stroke", "#313244").attr("stroke-width", 0.5).attr("opacity", 0.85);

    // Bar chart: horizontal bars, main=full opacity, input=dimmed same color
    let by = 3;
    const barsMaxW = barChartW - 6;
    kindEntries.forEach(([k, counts]) => {{
      const totalK = counts.main + counts.input;
      const fullW = Math.max(2, (totalK / maxCount) * barsMaxW);
      const mainW = Math.max(1, (counts.main / maxCount) * barsMaxW);
      const color = kindDot(k);

      // Input portion (dimmed, full width)
      if (counts.input > 0) {{
        sg.append("rect")
          .attr("x", 3).attr("y", by).attr("width", fullW).attr("height", barH).attr("rx", 1)
          .attr("fill", color).attr("opacity", 0.25);
      }}
      // Main portion (bright, overlaid)
      if (counts.main > 0) {{
        sg.append("rect")
          .attr("x", 3).attr("y", by).attr("width", mainW).attr("height", barH).attr("rx", 1)
          .attr("fill", color).attr("opacity", 0.85);
      }}
      // Tainted overlay: red stripe at bottom of bar
      // Count tainted in this kind for this layer
      let kindTainted = 0;
      lay.nodes.forEach(n => {{ if (n.kind === k && _allTainted.has(n.name)) kindTainted++; }});
      if (kindTainted > 0) {{
        const tw = Math.max(1, (kindTainted / maxCount) * barsMaxW);
        sg.append("rect")
          .attr("x", 3).attr("y", by + barH - 1.5).attr("width", tw).attr("height", 1.5).attr("rx", 0.5)
          .attr("fill", taintSources.has(k) ? "#f38ba8" : "#f38ba8").attr("opacity", 0.7);
      }}

      // Label to the right — full kind name
      sg.append("text")
        .attr("x", barChartW).attr("y", by + barH - 0.5)
        .attr("fill", color).attr("font-size", "5px").attr("opacity", 0.8)
        .text(`${{k}} ${{totalK}}`);
      by += barH + 1;
    }});

    // ── Taint summary: big numbers below bars ──
    const ty = panelH + 1;
    let tx = 4;
    if (allUnverified > 0) {{
      sg.append("text").attr("x", tx).attr("y", ty + 7)
        .attr("fill", "#f38ba8").attr("font-size", "7px").attr("font-weight", "bold")
        .text(`${{allUnverified}}/${{pct(allUnverified, allTotal)}}%`);
      tx += (`${{allUnverified}}/${{pct(allUnverified, allTotal)}}%`).length * 4 + 2;
      sg.append("text").attr("x", tx).attr("y", ty + 7)
        .attr("fill", "#f38ba8").attr("font-size", "5px").attr("opacity", 0.7)
        .text(`unverified`);
      tx += 32;
    }}
    if (allPropagated > 0) {{
      sg.append("text").attr("x", tx).attr("y", ty + 7)
        .attr("fill", "#f9e2af").attr("font-size", "7px").attr("font-weight", "bold")
        .text(`${{allPropagated}}/${{pct(allPropagated, allTotal)}}%`);
      tx += (`${{allPropagated}}/${{pct(allPropagated, allTotal)}}%`).length * 4 + 2;
      sg.append("text").attr("x", tx).attr("y", ty + 7)
        .attr("fill", "#f9e2af").attr("font-size", "5px").attr("opacity", 0.7)
        .text(`tainted`);
    }}
    if (allUnverified === 0 && allPropagated === 0) {{
      sg.append("text").attr("x", tx).attr("y", ty + 7)
        .attr("fill", "#a6e3a1").attr("font-size", "5.5px").attr("opacity", 0.7)
        .text('\u2713 clean');
    }}
  }});

  // ── Helper: draw bezier between two positioned elements ──
  function bezier(sp, tp, fromRight, toLeft) {{
    const x1 = fromRight ? sp.x + sp.w : sp.x;
    const y1 = sp.y + sp.h / 2;
    const x2 = toLeft ? tp.x : tp.x + tp.w;
    const y2 = tp.y + tp.h / 2;
    if (Math.abs(x2 - x1) < 2) {{
      // Vertical: arc left
      const xBase = Math.min(sp.x, tp.x);
      const arcW = 16 + Math.abs(y2 - y1) * 0.05;
      return `M${{xBase}},${{y1}} C${{xBase-arcW}},${{y1}} ${{xBase-arcW}},${{y2}} ${{xBase}},${{y2}}`;
    }}
    const dx = (x2 - x1) * 0.35;
    return `M${{x1}},${{y1}} C${{x1+dx}},${{y1}} ${{x2-dx}},${{y2}} ${{x2}},${{y2}}`;
  }}

  // ── Draw edges routed through input pills ──
  const edgeEls = [];
  const drawnSourceToInp = new Set();  // avoid duplicate source→inp lines
  // Build layerIdx lookup for targets
  const nodeLayerIdx = {{}};
  LAYERS.layers.forEach((lay, li) => {{ lay.nodes.forEach(n => {{ nodeLayerIdx[n.name] = li; }}); }});

  LAYERS.edges.forEach(e => {{
    const sp = pos[e.source];
    const tp = pos[e.target];
    const color = TYPE_COLOR[e.type] || '#a6adc8';

    if (e.type === 'use' || e.type === 'declare') {{
      // Route through deduped input pill
      const li = nodeLayerIdx[e.target];
      if (li === undefined || !tp) return;
      const inpId = 'inp:' + e.source + '@' + li;
      const ip = pos[inpId];
      if (ip) {{
        // Segment 1: source → input pill (only if source is in view)
        if (sp) {{
          const seg1Key = e.source + '>' + inpId;
          if (!drawnSourceToInp.has(seg1Key)) {{
            drawnSourceToInp.add(seg1Key);
            const d1 = bezier(sp, ip, true, true);
            const el1 = g.append("path")
              .attr("d", d1).attr("fill", "none").attr("stroke", color)
              .attr("stroke-opacity", 0.2).attr("stroke-width", 1.2)
              .attr("data-source", e.source).attr("data-target", e.target).attr("data-type", e.type)
              .attr("data-seg", "1").node();
            edgeEls.push(el1);
          }}
        }}
        // Segment 2: input pill → consumer result (always drawn)
        const d2 = bezier(ip, tp, true, true);
        const el2 = g.append("path")
          .attr("d", d2).attr("fill", "none").attr("stroke", color)
          .attr("stroke-opacity", 0.2).attr("stroke-width", 1.2)
          .attr("data-source", e.source).attr("data-target", e.target).attr("data-type", e.type)
          .attr("data-seg", "2").node();
        edgeEls.push(el2);
      }} else if (sp && tp) {{
        // Fallback direct
        const d = bezier(sp, tp, true, true);
        const el = g.append("path").attr("d", d).attr("fill", "none").attr("stroke", color)
          .attr("stroke-opacity", 0.2).attr("stroke-width", 1.2)
          .attr("data-source", e.source).attr("data-target", e.target).attr("data-type", e.type).node();
        edgeEls.push(el);
      }}
    }} else {{
      if (!sp || !tp) return;
      // Direct connection: pull, axiom-ref
      const d = bezier(sp, tp, sp.depth !== tp.depth, sp.depth !== tp.depth);
      const el = g.append("path")
        .attr("d", d).attr("fill", "none").attr("stroke", color)
        .attr("stroke-opacity", e.type === 'axiom-ref' ? 0.35 : 0.2)
        .attr("stroke-width", 1.2)
        .attr("data-source", e.source).attr("data-target", e.target).attr("data-type", e.type)
        .node();
      edgeEls.push(el);
    }}
  }});

  // ── Draw input sub-pills ──
  Object.entries(inputPillData).forEach(([id, inp]) => {{
    const p = pos[id];
    if (!p) return;
    const stroke = TYPE_STROKE[inp.type] || '#585b70';
    const isDeclare = inp.type === 'declare';

    const pg = g.append("g")
      .attr("transform", `translate(${{p.x}},${{p.y}})`)
      .attr("class", "cursor-pointer pill-node pill-input").attr("data-name", inp.label);

    pg.append("rect")
      .attr("width", p.w).attr("height", SUB_PH).attr("rx", 9)
      .attr("fill", isDeclare ? '#1e1e2e' : '#262637')
      .attr("stroke", stroke).attr("stroke-width", 1)
      .attr("stroke-dasharray", isDeclare ? '3,2' : 'none');

    const short = inp.label.includes('.') ? inp.label.split('.').slice(1).join('.') : inp.label;
    const maxCh = Math.floor((p.w - 16) / 5.2);
    pg.append("text")
      .attr("x", 8).attr("y", SUB_PH / 2 + 1).attr("dominant-baseline", "middle")
      .attr("fill", stroke).attr("font-size", "8.5px")
      .text((inp.type === 'use' ? ':use ' + short : ':' + short).slice(0, maxCh));

    pg.on("mouseover", (ev) => {{
      tooltip.html(`<b>:${{inp.label}}</b>\\ntype: ${{inp.type}}\\nconsumer: ${{inp.consumer}}`)
        .classed("hidden", false)
        .style("left", (ev.pageX + 12) + "px").style("top", (ev.pageY - 8) + "px");
    }}).on("mouseout", () => {{ tooltip.classed("hidden", true); }});
    pg.on("click", (ev) => {{
      ev.stopPropagation();
      focusNode(inp.label);
    }});
  }});

  // ── Draw result pills ──
  Object.entries(pos).forEach(([name, p]) => {{
    if (p.isInput) return;
    const n = nodeData[name];
    if (!n) return;

    const pg = g.append("g")
      .attr("transform", `translate(${{p.x}},${{p.y}})`)
      .attr("class", "cursor-pointer pill-node pill-result").attr("data-name", name);

    pg.append("rect")
      .attr("width", p.w).attr("height", PH).attr("rx", 14)
      .attr("fill", "#313244").attr("stroke", kindDot(n.kind)).attr("stroke-width", 1.5);
    pg.append("circle")
      .attr("cx", 12).attr("cy", PH / 2).attr("r", 4).attr("fill", kindDot(n.kind));

    const short = name.includes('.') ? name.split('.').slice(1).join('.') : name;
    const valS = n.value ? ` =${{String(n.value).slice(0,15)}}` : '';
    const maxCh = Math.floor((p.w - 28) / 6);
    pg.append("text")
      .attr("x", 22).attr("y", PH / 2 + 1).attr("dominant-baseline", "middle")
      .attr("fill", "#cdd6f4").attr("font-size", "10px")
      .text((short + valS).slice(0, maxCh));

    pg.on("mouseover", (ev) => {{
      let html = `<b>${{name}}</b>\\nkind: ${{n.kind}}`;
      if (n.value) html += `\\nvalue: ${{String(n.value).slice(0,100)}}`;
      if (n.uses && n.uses.length) html += `\\nuses: ${{n.uses.join(', ')}}`;
      if (n.declares && n.declares.length) html += `\\ndeclares: ${{n.declares.join(', ')}}`;
      if (n.pulls && n.pulls.length) html += `\\npulls: ${{n.pulls.join(', ')}}`;
      const downs = childrenOf[name] || [];
      if (downs.length) html += `\\ndownstream: ${{downs.join(', ')}}`;
      tooltip.html(html).classed("hidden", false)
        .style("left", (ev.pageX + 12) + "px").style("top", (ev.pageY - 8) + "px");
    }}).on("mouseout", () => {{ tooltip.classed("hidden", true); }});
    pg.on("click", (ev) => {{
      ev.stopPropagation();
      focusNode(name);
    }});
  }});

  // ── Hanging section: disconnected L0 nodes ──
  if (hangingNodes.length > 0) {{
    // Find max Y from all positioned elements to place hanging below
    let maxY = 0;
    Object.values(pos).forEach(p => {{ maxY = Math.max(maxY, p.y + p.h); }});
    const hangY = maxY + 40;

    g.append("text")
      .attr("x", PAD).attr("y", hangY)
      .attr("fill", "#585b70").attr("font-size", "11px").attr("font-weight", "bold")
      .attr("class", "layer-label")
      .text(`Hanging (${{hangingNodes.length}})`);
    g.append("line")
      .attr("x1", PAD).attr("y1", hangY + 4)
      .attr("x2", PAD + 200).attr("y2", hangY + 4)
      .attr("stroke", "#585b70").attr("stroke-width", 0.5)
      .attr("class", "layer-label");

    const hangSet = new Set(hangingNodes.map(n => n.name));
    const HANG_W = 180;

    // Collect internal edges among hanging nodes
    const hangEdges = [];
    const hangFwd = {{}};
    const hangInDeg = {{}};
    hangingNodes.forEach(n => {{ hangInDeg[n.name] = 0; }});
    LAYERS.edges.forEach(e => {{
      if (hangSet.has(e.source) && hangSet.has(e.target)) {{
        hangEdges.push(e);
        if (!hangFwd[e.source]) hangFwd[e.source] = [];
        hangFwd[e.source].push(e.target);
        hangInDeg[e.target] = (hangInDeg[e.target] || 0) + 1;
      }}
    }});

    // Topological layers for DAG layout
    const hangLayers = [];
    const hangAssigned = new Set();
    // Start with roots (in-degree 0)
    let frontier = hangingNodes.filter(n => (hangInDeg[n.name] || 0) === 0).map(n => n.name);
    while (frontier.length) {{
      hangLayers.push(frontier);
      frontier.forEach(n => hangAssigned.add(n));
      const next = new Set();
      frontier.forEach(n => {{
        (hangFwd[n] || []).forEach(t => {{
          if (!hangAssigned.has(t)) next.add(t);
        }});
      }});
      // Only include nodes whose ALL parents are assigned
      frontier = [...next].filter(n => {{
        const parents = LAYERS.edges.filter(e => e.target === n && hangSet.has(e.source)).map(e => e.source);
        return parents.every(p => hangAssigned.has(p));
      }});
      if (frontier.length === 0 && hangAssigned.size < hangingNodes.length) {{
        // Remaining unassigned (cycles) — dump them
        const remaining = hangingNodes.filter(n => !hangAssigned.has(n.name)).map(n => n.name);
        hangLayers.push(remaining);
        remaining.forEach(n => hangAssigned.add(n));
      }}
    }}

    // Layout hanging nodes in LTR columns per topo layer
    const hangNodeMap = {{}};
    hangingNodes.forEach(n => {{ hangNodeMap[n.name] = n; }});

    let hx = PAD;
    hangLayers.forEach(layer => {{
      let hy = hangY + 14;
      // Measure col width
      let colW = HANG_W;
      layer.forEach(name => {{
        const short = name.includes('.') ? name.split('.').slice(1).join('.') : name;
        colW = Math.max(colW, Math.min(220, short.length * 6.5 + 28));
      }});

      layer.forEach(name => {{
        const n = hangNodeMap[name];
        if (!n) return;
        nodeData[n.name] = n;
        pos[n.name] = {{ x: hx, y: hy, w: colW, h: PH, depth: 0, hanging: true }};

        const pg = g.append("g")
          .attr("transform", `translate(${{hx}},${{hy}})`)
          .attr("class", "cursor-pointer pill-node pill-result").attr("data-name", n.name);
        pg.append("rect")
          .attr("width", colW).attr("height", PH).attr("rx", 14)
          .attr("fill", "#1e1e2e").attr("stroke", "#585b70").attr("stroke-width", 1)
          .attr("stroke-dasharray", "4,2");
        pg.append("circle")
          .attr("cx", 12).attr("cy", PH / 2).attr("r", 4).attr("fill", kindDot(n.kind));
        const short = n.name.includes('.') ? n.name.split('.').slice(1).join('.') : n.name;
        pg.append("text")
          .attr("x", 22).attr("y", PH / 2 + 1).attr("dominant-baseline", "middle")
          .attr("fill", "#585b70").attr("font-size", "10px")
          .text(short.slice(0, Math.floor((colW - 28) / 6)));
        pg.on("mouseover", (ev) => {{
          tooltip.html(`<b>${{n.name}}</b>\\nkind: ${{n.kind}}\\n(hanging)`)
            .classed("hidden", false)
            .style("left", (ev.pageX + 12) + "px").style("top", (ev.pageY - 8) + "px");
        }}).on("mouseout", () => {{ tooltip.classed("hidden", true); }});
        pg.on("click", (ev) => {{
          ev.stopPropagation();
          const d = ITEM_BY_ID[n.name];
          if (d) showDetail(d);
        }});
        hy += PH + GAP_Y;
      }});
      hx += colW + 30;
    }});

    // Draw internal edges among hanging nodes
    hangEdges.forEach(e => {{
      const sp = pos[e.source];
      const tp = pos[e.target];
      if (!sp || !tp) return;
      const color = TYPE_COLOR[e.type] || '#585b70';
      const sameCol = sp.x === tp.x;
      const d = sameCol
        ? bezier(sp, tp, false, false)
        : bezier(sp, tp, true, true);
      g.append("path")
        .attr("d", d).attr("fill", "none").attr("stroke", color)
        .attr("stroke-opacity", 0.3).attr("stroke-width", 1)
        .attr("stroke-dasharray", "4,2");
    }});
  }}

  // ── Focus mode toggle ──
  const btnFocus = document.getElementById('btn-focus-mode');
  const btnUnfocus = document.getElementById('btn-unfocus');

  function syncFocusBtnStyle() {{
    btnFocus.textContent = focusMode ? 'Focus ON' : 'Focus mode';
    btnFocus.className = focusMode
      ? 'px-3 py-1 rounded-lg text-xs bg-mauve text-crust font-bold border border-mauve'
      : 'px-3 py-1 rounded-lg text-xs bg-surface0 text-subtext border border-surface2 hover:bg-surface1';
  }}
  btnFocus.onclick = () => {{
    focusMode = !focusMode;
    syncFocusBtnStyle();
    if (focusMode && focusedId) focusNode(focusedId);
    else if (!focusMode) unfocusAll();
  }};
  btnUnfocus.onclick = () => unfocusAll();
  svg.on("click", () => {{ if (!focusMode) unfocusAll(); }});

  // ── Taint propagation (visual) ──
  let taintsOn = false;
  const btnTaints = document.getElementById('btn-taints');

  function applyTaints() {{
    const tainted = computeTainted();
    g.selectAll(".pill-result").each(function() {{
      const el = d3.select(this);
      const name = el.attr("data-name");
      if (tainted.has(name)) {{
        const isSource = taintSources.has(name);
        el.select("rect")
          .attr("stroke", isSource ? "#f38ba8" : "#f9e2af")
          .attr("stroke-width", isSource ? 2.5 : 2)
          .attr("stroke-dasharray", isSource ? "none" : "6,2");
      }}
    }});
    g.selectAll(".pill-input").each(function() {{
      const el = d3.select(this);
      const name = el.attr("data-name");
      if (tainted.has(name)) {{
        el.select("rect").attr("stroke", "#f9e2af").attr("stroke-width", 1.5);
      }}
    }});
    edgeEls.forEach(el => {{
      const s = el.getAttribute("data-source");
      const t = el.getAttribute("data-target");
      if (tainted.has(s) && tainted.has(t)) {{
        el.setAttribute("stroke", "#f9e2af");
        el.setAttribute("stroke-opacity", "0.5");
        el.setAttribute("stroke-width", "1.8");
      }}
    }});
    // Show count
    info.innerHTML = `<div class="font-bold text-red mb-1">Taint analysis</div>`
      + `<div><span class="text-overlay0">sources:</span> <span class="text-red">${{taintSources.size}}</span> unverified</div>`
      + `<div><span class="text-overlay0">tainted:</span> <span class="text-yellow">${{tainted.size}}</span> total</div>`
      + `<div class="mt-1 text-[10px] text-overlay0">Red = unverified source, Yellow = tainted downstream</div>`;
    info.classList.remove("hidden");
  }}

  function clearTaints() {{
    g.selectAll(".pill-result").each(function() {{
      const el = d3.select(this);
      const name = el.attr("data-name");
      const n = nodeData[name];
      const p = pos[name];
      if (n && p && !p.hanging) {{
        el.select("rect").attr("stroke", kindDot(n.kind)).attr("stroke-width", 1.5).attr("stroke-dasharray", "none");
      }} else if (p && p.hanging) {{
        el.select("rect").attr("stroke", "#585b70").attr("stroke-width", 1).attr("stroke-dasharray", "4,2");
      }}
    }});
    g.selectAll(".pill-input").each(function() {{
      const el = d3.select(this);
      el.select("rect").attr("stroke", "#a6e3a1").attr("stroke-width", 1);
    }});
    edgeEls.forEach(el => {{
      const t = el.getAttribute("data-type");
      el.setAttribute("stroke", TYPE_COLOR[t] || '#a6adc8');
      el.setAttribute("stroke-opacity", t === 'axiom-ref' ? "0.35" : "0.2");
      el.setAttribute("stroke-width", "1.2");
    }});
    info.classList.add("hidden");
  }}

  function applyFocusTaints() {{
    if (!focusG) return;
    const tainted = computeTainted();
    focusG.selectAll(".fpill-result").each(function() {{
      const el = d3.select(this);
      const name = el.attr("data-name");
      if (tainted.has(name)) {{
        const isSource = taintSources.has(name);
        el.select("rect")
          .attr("stroke", isSource ? "#f38ba8" : "#f9e2af")
          .attr("stroke-width", isSource ? 2.5 : 2)
          .attr("stroke-dasharray", isSource ? "none" : "6,2");
      }}
    }});
    focusG.selectAll(".fpill-input").each(function() {{
      const el = d3.select(this);
      const name = el.attr("data-name");
      if (tainted.has(name)) {{
        el.select("rect").attr("stroke", "#f9e2af").attr("stroke-width", 1.5);
      }}
    }});
  }}

  function clearFocusTaints() {{
    if (!focusG) return;
    focusG.selectAll(".fpill-result").each(function() {{
      const el = d3.select(this);
      const name = el.attr("data-name");
      const n = nodeData[name];
      el.select("rect").attr("stroke", kindDot(n ? n.kind : '')).attr("stroke-width", 1.5).attr("stroke-dasharray", "none");
    }});
    focusG.selectAll(".fpill-input").each(function() {{
      const el = d3.select(this);
      el.select("rect").attr("stroke", TYPE_STROKE[el.attr("data-type")] || '#585b70').attr("stroke-width", 1);
    }});
  }}

  btnTaints.onclick = () => {{
    taintsOn = !taintsOn;
    btnTaints.textContent = taintsOn ? 'Taints ON' : 'Taints';
    btnTaints.className = taintsOn
      ? 'px-3 py-1 rounded-lg text-xs bg-red text-crust font-bold border border-red'
      : 'px-3 py-1 rounded-lg text-xs bg-surface0 text-subtext border border-surface2 hover:bg-surface1';
    if (taintsOn) {{ applyTaints(); applyFocusTaints(); }}
    else {{ clearTaints(); clearFocusTaints(); }}
  }};

  function focusNode(id) {{
    focusedId = id;
    const path = collectPath(id);
    btnUnfocus.classList.remove("hidden");

    if (focusMode) {{
      rebuildFocused(path, id);
      return;
    }}

    // ── Dim mode: dim non-path, highlight path ──
    g.selectAll(".pill-node").each(function() {{
      const el = d3.select(this);
      const name = el.attr("data-name");
      if (path.has(name)) {{
        el.attr("opacity", 1);
        if (name === id) el.select("rect").attr("stroke", "#cba6f7").attr("stroke-width", 3);
        else el.select("rect").attr("stroke-width", el.classed("pill-input") ? 1 : 1.5);
      }} else {{
        el.attr("opacity", 0.08);
      }}
    }});

    edgeEls.forEach(el => {{
      const s = el.getAttribute("data-source");
      const t = el.getAttribute("data-target");
      if (path.has(s) && path.has(t)) {{
        el.setAttribute("stroke-opacity", "0.8");
        el.setAttribute("stroke-width", "2");
      }} else {{
        el.setAttribute("stroke-opacity", "0.03");
        el.setAttribute("stroke-width", "1");
      }}
    }});

    g.selectAll(".layer-label").attr("opacity", 0.15);

    const d = ITEM_BY_ID[id];
    if (d) {{
      info.innerHTML = _infoHtml(d, path);
      info.classList.remove("hidden");
      showDetail(d);
    }}
  }}

  // ── Rebuild SVG with only focused path nodes (rails-but-pills layout) ──
  let focusG = null;
  function rebuildFocused(path, focusId) {{
    g.selectAll("*").style("display", "none");
    if (focusG) focusG.remove();
    focusG = svg.append("g");
    svg.call(zoomBehavior);
    zoomBehavior.on("zoom", (e) => focusG.attr("transform", e.transform));

    // Filter layers to path nodes
    const fLayers = [];
    LAYERS.layers.forEach(lay => {{
      const fnodes = lay.nodes.filter(n => path.has(n.name));
      if (fnodes.length) fLayers.push({{ depth: lay.depth, nodes: fnodes }});
    }});

    const fPos = {{}};
    const fInputPills = {{}};
    const fNodeLayerIdx = {{}};
    let fX = PAD;

    fLayers.forEach((lay, li) => {{
      lay.nodes.forEach(n => {{ fNodeLayerIdx[n.name] = li; }});

      // Deduped input pills for this layer (uses + declares)
      const useSeen = {{}};
      const layerInputs = [];
      lay.nodes.forEach(n => {{
        (n.uses || []).forEach(u => {{
          if (path.has(u) || path.has(n.name)) {{
            if (!useSeen[u]) {{
              useSeen[u] = {{id: 'inp:'+u+'@'+li, label: u, consumers: [], type: 'use'}};
              layerInputs.push(useSeen[u]);
            }}
            useSeen[u].consumers.push(n.name);
          }}
        }});
        (n.declares || []).forEach(d => {{
          if (path.has(d) || path.has(n.name)) {{
            if (!useSeen[d]) {{
              useSeen[d] = {{id: 'inp:'+d+'@'+li, label: d, consumers: [], type: 'declare'}};
              layerInputs.push(useSeen[d]);
            }}
            useSeen[d].consumers.push(n.name);
          }}
        }});
      }});
      layerInputs.forEach(p => {{ fInputPills[p.id] = p; }});
      const hasInputs = layerInputs.length > 0;

      // Measure widths
      let inputColW = 0;
      if (hasInputs) layerInputs.forEach(inp => {{
        const short = inp.label.includes('.') ? inp.label.split('.').slice(1).join('.') : inp.label;
        inp._w = Math.min(SPW_MAX, Math.max(SPW_MIN, short.length * 5.5 + 20));
        inputColW = Math.max(inputColW, inp._w);
      }});
      let resultColW = 0;
      lay.nodes.forEach(n => {{
        const short = n.name.includes('.') ? n.name.split('.').slice(1).join('.') : n.name;
        n._fw = Math.min(PW_MAX, Math.max(PW_MIN, (short + (n.value ? ' =' + String(n.value).slice(0,15) : '')).length * 6.5 + 28));
        resultColW = Math.max(resultColW, n._fw);
      }});

      const inputXf = fX;
      const resultXf = hasInputs ? fX + inputColW + GAP_XI : fX;

      focusG.append("text")
        .attr("x", fX + (resultXf + resultColW - fX) / 2).attr("y", PAD + 12)
        .attr("text-anchor", "middle")
        .attr("fill", "#6c7086").attr("font-size", "10px").attr("font-weight", "bold")
        .text(`L${{lay.depth}}`);

      // Stack input pills
      let inputY = PAD + LABEL_H;
      layerInputs.forEach(inp => {{
        fPos[inp.id] = {{ x: inputXf, y: inputY, w: inp._w, h: SUB_PH, isInput: true, type: inp.type }};
        inputY += SUB_PH + SUB_GAP_Y;
      }});
      // Stack result pills
      let resultY = PAD + LABEL_H;
      lay.nodes.forEach(n => {{
        fPos[n.name] = {{ x: resultXf, y: resultY, w: n._fw, h: PH }};
        resultY += PH + GAP_Y;
      }});
      fX = resultXf + resultColW + GAP_X;
    }});

    // Draw focused edges
    const fDrawnSrcInp = new Set();
    LAYERS.edges.forEach(e => {{
      const sp = fPos[e.source];
      const tp = fPos[e.target];
      const color = TYPE_COLOR[e.type] || '#a6adc8';

      if (e.type === 'use' || e.type === 'declare') {{
        const li = fNodeLayerIdx[e.target];
        if (li === undefined || !tp) return;
        const inpId = 'inp:' + e.source + '@' + li;
        const ip = fPos[inpId];
        if (ip) {{
          if (sp) {{
            const seg1Key = e.source + '>' + inpId;
            if (!fDrawnSrcInp.has(seg1Key)) {{
              fDrawnSrcInp.add(seg1Key);
              focusG.append("path").attr("d", bezier(sp, ip, true, true))
                .attr("fill", "none").attr("stroke", color).attr("stroke-opacity", 0.6).attr("stroke-width", 1.8);
            }}
          }}
          focusG.append("path").attr("d", bezier(ip, tp, true, true))
            .attr("fill", "none").attr("stroke", color).attr("stroke-opacity", 0.6).attr("stroke-width", 1.8);
        }} else if (sp && tp) {{
          focusG.append("path").attr("d", bezier(sp, tp, true, true))
            .attr("fill", "none").attr("stroke", color).attr("stroke-opacity", 0.6).attr("stroke-width", 1.8);
        }}
      }} else {{
        if (!sp || !tp) return;
        focusG.append("path").attr("d", bezier(sp, tp, true, true))
          .attr("fill", "none").attr("stroke", color)
          .attr("stroke-opacity", e.type === 'axiom-ref' ? 0.5 : 0.6).attr("stroke-width", 1.8);
      }}
    }});

    // Draw focused input pills
    Object.entries(fInputPills).forEach(([id, inp]) => {{
      const p = fPos[id];
      if (!p) return;
      const stroke = TYPE_STROKE[inp.type] || '#585b70';
      const pg = focusG.append("g").attr("transform", `translate(${{p.x}},${{p.y}})`).attr("class", "cursor-pointer fpill-input").attr("data-name", inp.label);
      pg.append("rect").attr("width", p.w).attr("height", SUB_PH).attr("rx", 9)
        .attr("fill", '#262637').attr("stroke", stroke).attr("stroke-width", 1);
      const short = inp.label.includes('.') ? inp.label.split('.').slice(1).join('.') : inp.label;
      pg.append("text").attr("x", 8).attr("y", SUB_PH / 2 + 1).attr("dominant-baseline", "middle")
        .attr("fill", stroke).attr("font-size", "8.5px")
        .text((inp.type === 'use' ? ':use ' + short : ':' + short).slice(0, Math.floor((p.w - 16) / 5.2)));
      pg.on("click", (ev) => {{
        ev.stopPropagation();
        const np = collectPath(inp.label);
        rebuildFocused(np, inp.label);
        const d = ITEM_BY_ID[inp.label];
        if (d) {{ info.innerHTML = _infoHtml(d, np); info.classList.remove("hidden"); showDetail(d); }}
      }});
    }});

    // Draw focused result pills
    fLayers.forEach(lay => lay.nodes.forEach(n => {{
      const p = fPos[n.name];
      if (!p || p.isInput) return;
      const isFocused = n.name === focusId;
      const pg = focusG.append("g").attr("transform", `translate(${{p.x}},${{p.y}})`).attr("class", "cursor-pointer fpill-result").attr("data-name", n.name);
      pg.append("rect").attr("width", p.w).attr("height", PH).attr("rx", 14)
        .attr("fill", isFocused ? "#45475a" : "#313244")
        .attr("stroke", isFocused ? "#cba6f7" : kindDot(n.kind))
        .attr("stroke-width", isFocused ? 3 : 1.5);
      pg.append("circle").attr("cx", 12).attr("cy", PH / 2).attr("r", 4).attr("fill", kindDot(n.kind));
      const short = n.name.includes('.') ? n.name.split('.').slice(1).join('.') : n.name;
      const maxCh = Math.floor((p.w - 28) / 6);
      pg.append("text").attr("x", 22).attr("y", PH / 2 + 1).attr("dominant-baseline", "middle")
        .attr("fill", "#cdd6f4").attr("font-size", "10px")
        .text((short + (n.value ? ' =' + String(n.value).slice(0,15) : '')).slice(0, maxCh));
      pg.on("click", (ev) => {{
        ev.stopPropagation();
        const np = collectPath(n.name);
        rebuildFocused(np, n.name);
        const d = ITEM_BY_ID[n.name];
        if (d) {{ info.innerHTML = _infoHtml(d, np); info.classList.remove("hidden"); showDetail(d); }}
      }});
      pg.on("mouseover", (ev) => {{
        tooltip.html(`<b>${{n.name}}</b>\\n${{n.kind}}${{n.value ? '\\n' + String(n.value).slice(0,80) : ''}}`)
          .classed("hidden", false)
          .style("left", (ev.pageX + 12) + "px").style("top", (ev.pageY - 8) + "px");
      }}).on("mouseout", () => tooltip.classed("hidden", true));
    }}));

    // Apply taints if active
    if (taintsOn) applyFocusTaints();

    // Info + zoom to fit
    const d = ITEM_BY_ID[focusId];
    if (d) {{ info.innerHTML = _infoHtml(d, path); info.classList.remove("hidden"); showDetail(d); }}
    requestAnimationFrame(() => {{
      const bounds = focusG.node().getBBox();
      if (bounds.width > 0) {{
        const scale = Math.min(W / (bounds.width + 80), H / (bounds.height + 80), 2);
        const cx = bounds.x + bounds.width / 2, cy = bounds.y + bounds.height / 2;
        svg.transition().duration(300).call(
          zoomBehavior.transform,
          d3.zoomIdentity.translate(W/2 - cx*scale, H/2 - cy*scale).scale(scale)
        );
      }}
    }});
  }}

  function unfocusAll() {{
    focusedId = null;
    focusMode = false;
    syncFocusBtnStyle();
    btnUnfocus.classList.add("hidden");
    if (focusG) {{ focusG.remove(); focusG = null; }}
    g.selectAll("*").style("display", null);
    zoomBehavior.on("zoom", (e) => g.attr("transform", e.transform));

    g.selectAll(".pill-result").attr("opacity", 1).each(function() {{
      const el = d3.select(this);
      const name = el.attr("data-name");
      const n = nodeData[name];
      el.select("rect").attr("stroke-width", 1.5).attr("stroke", kindDot(n ? n.kind : ''));
    }});
    g.selectAll(".pill-input").attr("opacity", 1);
    edgeEls.forEach(el => {{
      el.setAttribute("stroke-opacity", "0.2");
      el.setAttribute("stroke-width", "1.2");
    }});
    g.selectAll(".layer-label").attr("opacity", 1);
    info.classList.add("hidden");

    // Restore taints if active
    if (taintsOn) applyTaints();

    requestAnimationFrame(() => {{
      const bounds = g.node().getBBox();
      if (bounds.width > 0) {{
        const scale = Math.min(W / (bounds.width + 80), H / (bounds.height + 80), 1);
        const tx = 40 - bounds.x * scale, ty = 20 - bounds.y * scale;
        svg.transition().duration(300).call(
          zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
        );
      }}
    }});
  }}

  function _infoHtml(d, path) {{
    let html = `<div class="font-bold text-lavender mb-1">${{esc(d.id)}}</div>`;
    html += `<div><span class="text-overlay0">kind:</span> <span style="color:${{kindDot(d.kind)}}">${{esc(d.kind)}}</span></div>`;
    html += `<div><span class="text-overlay0">layer:</span> ${{d.depth}}</div>`;
    html += `<div><span class="text-overlay0">path:</span> ${{path.size}} nodes</div>`;
    const downs = childrenOf[d.id] || [];
    if (downs.length) html += `<div><span class="text-overlay0">downstream:</span> ${{downs.length}}</div>`;
    if (d.value) html += `<div class="mt-1 text-subtext truncate" style="max-width:250px">${{esc(String(d.value).slice(0,80))}}</div>`;
    return html;
  }}

  // Initial zoom to fit
  requestAnimationFrame(() => {{
    const bounds = g.node().getBBox();
    if (bounds.width > 0 && bounds.height > 0) {{
      const scale = Math.min(W / (bounds.width + 80), H / (bounds.height + 80), 1);
      const tx = 40 - bounds.x * scale;
      const ty = 20 - bounds.y * scale;
      svg.call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
    }}
  }});
}}

// ── Init ──
render();
</script>
</body>
</html>
"""
