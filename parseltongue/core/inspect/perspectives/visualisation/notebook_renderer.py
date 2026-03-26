"""NotebookRenderer — extends the viz app with a Notebook view for .pgmd files.

Reads app.html as the single source of truth, injects notebook tab/view/JS
via Python transformation, then substitutes data as usual.  No template
duplication — the notebook is composed on top of the existing viz app.

Usage::

    from parseltongue.core.inspect.perspectives.visualisation.notebook_renderer import render_notebook

    html = render_notebook(
        title="Q3 Analysis",
        notebook_html="<div>...</div>",   # pre-rendered prose + blocks
        items=items,                       # viz DATA items (from structure)
        structure_items=structure_items,    # STRUCTURE_DATA items
        layers_data=layers_data,           # LAYERS dict
    )
"""

from __future__ import annotations

import html as html_mod
import json
import re
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Any

from .renderer import (
    _build_layers_data,
    _enrich_items_from_structure,
    _html_escape,
    _localize_multi,
    _strip_internal,
)

if TYPE_CHECKING:
    from ...probe_core_to_consequence import CoreToConsequenceStructure

_TEMPLATES = Path(__file__).parent / "templates"


def _read(name: str) -> str:
    return (_TEMPLATES / name).read_text()


# ── Kind colors (match core.js KIND_DOT_VAR) ──

_KIND_COLORS = {
    "fact": "green",
    "axiom": "peach",
    "theorem": "mauve",
    "calc": "blue",
    "term-fwd": "teal",
    "term-comp": "teal",
    "derive": "mauve",
    "defterm": "blue",
    "diff": "red",
    "synthetic": "overlay0",
}

_REF_RE = re.compile(r"([^\s,\[]*?)\[\[(~?)(\w+):([^\]]+)\]\]([^\s,.:;!?\[)]*)")


# ── Value formatting ──


def _fmt_value(val_str: str) -> str:
    """Format a value for display. No guessing — just clean up the raw encoding."""
    if not val_str:
        return ""
    # S-expression — already encoded by ParseltongueGrammar.enc
    if val_str.startswith("(") and val_str.endswith(")") and val_str != "()":
        return val_str
    # Silence
    if val_str == "()":
        return ""
    try:
        v = float(val_str)
        if v == int(v) and abs(v) >= 1_000_000:
            return f"{v / 1_000_000:.1f}M"
        if v == int(v) and abs(v) >= 1000:
            return f"{v:,.0f}"
        if 0 < abs(v) < 1:
            return f"{v:.2%}"
        if v == int(v):
            return str(int(v))
        return f"{v:.2f}"
    except (ValueError, OverflowError):
        if val_str in ("True", "true"):
            return "true"
        if val_str in ("False", "false"):
            return "false"
        return val_str[:40]


# ── Markdown → HTML with footnote-style refs ──

# Global footnote counter (reset per build_notebook_html call)
_footnote_counter: int = 0


def _wrap_with_margin(element_html: str, element_refs: list[dict]) -> str:
    """Wrap an HTML element with per-element margin pills if it introduced refs."""
    if not element_refs:
        return element_html
    pills = _render_margin_pills(element_refs)
    return (
        f'<div class="nb-prose-row relative">' f'{element_html}' f'<div class="nb-margin-notes">{pills}</div>' f'</div>'
    )


def _md_to_html(text: str, node_index: dict) -> tuple[str, list[dict]]:
    """Convert markdown to HTML, returning (html, collected_refs).

    Refs become inline footnotes; collected_refs is a list of
    {num, name, node_id, kind, value} dicts for margin pill rendering.
    Each paragraph/heading/list gets its own margin pills aligned to it.
    """
    global _footnote_counter
    refs: list[dict] = []
    lines = text.strip().split("\n")
    out: list[str] = []
    in_list = False
    list_start = 0  # index into refs where current list began
    list_lines: list[str] = []  # list item HTML accumulated

    def _flush_list():
        nonlocal in_list, list_start, list_lines
        if not in_list:
            return
        ul = '<ul class="list-disc ml-6 mb-4 space-y-1">\n' + "\n".join(list_lines) + "\n</ul>"
        out.append(_wrap_with_margin(ul, refs[list_start:]))
        in_list = False
        list_lines = []

    for line in lines:
        s = line.strip()
        if s.startswith("### "):
            _flush_list()
            before = len(refs)
            html = f'<h3 class="text-lg font-bold text-mauve mt-6 mb-2">{_inline(s[4:], node_index, refs)}</h3>'
            out.append(_wrap_with_margin(html, refs[before:]))
        elif s.startswith("## "):
            _flush_list()
            before = len(refs)
            html = f'<h2 class="text-xl font-bold text-mauve mt-8 mb-3">{_inline(s[3:], node_index, refs)}</h2>'
            out.append(_wrap_with_margin(html, refs[before:]))
        elif s.startswith("# "):
            _flush_list()
            before = len(refs)
            html = f'<h1 class="text-2xl font-bold text-mauve mt-8 mb-4">{_inline(s[2:], node_index, refs)}</h1>'
            out.append(_wrap_with_margin(html, refs[before:]))
        elif s.startswith("- "):
            if not in_list:
                in_list = True
                list_start = len(refs)
                list_lines = []
            list_lines.append(f"<li>{_inline(s[2:], node_index, refs)}</li>")
        elif not s:
            _flush_list()
            out.append("")
        else:
            _flush_list()
            before = len(refs)
            html = f'<p class="mb-3 leading-relaxed">{_inline(s, node_index, refs)}</p>'
            out.append(_wrap_with_margin(html, refs[before:]))
    _flush_list()
    return "\n".join(out), refs


def _inline(text: str, node_index: dict, refs: list[dict] | None = None) -> str:
    global _footnote_counter
    text = html_mod.escape(text)
    text = re.sub(r"`([^`]+)`", r'<code class="bg-surface0 px-1.5 py-0.5 rounded text-peach text-sm">\1</code>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)

    def _ref_replace(m):
        global _footnote_counter
        prefix = m.group(1)  # e.g. "$" or "**" before [[
        silent = bool(m.group(2))  # ~ prefix
        ref_type, ref_name = m.group(3), m.group(4)
        suffix = m.group(5)  # e.g. "%" or "x" after ]]
        node = _resolve_node(ref_name, node_index)
        if node:
            color = _KIND_COLORS.get(node["kind"], "subtext")
            val = _fmt_value(node["value"])
            _footnote_counter += 1
            fn_num = _footnote_counter
            if refs is not None:
                refs.append(
                    {
                        "num": fn_num,
                        "name": ref_name,
                        "node_id": node["id"],
                        "kind": node["kind"],
                        "value": val,
                        "silent": silent,
                    }
                )
            if silent:
                return (
                    f'{prefix}<span class="nb-fn cursor-pointer" '
                    f'data-node="{html_mod.escape(node["id"])}" data-fn="{fn_num}">'
                    f'<sup class="text-{color} text-[0.65em] font-bold">{fn_num}</sup></span>{suffix}'
                )
            val_display = html_mod.escape(val) if val else html_mod.escape(ref_name)
            return (
                f'<span class="nb-fn text-{color} font-semibold cursor-pointer '
                f'hover:underline decoration-dotted" '
                f'data-node="{html_mod.escape(node["id"])}" data-fn="{fn_num}">'
                f'{prefix}{val_display}{suffix}<sup class="text-{color} text-[0.6em] ml-0.5">{fn_num}</sup></span>'
            )
        return f'{prefix}<span class="text-overlay0">{ref_type}:{ref_name}</span>{suffix}'

    text = _REF_RE.sub(_ref_replace, text)
    # Prevent clustering: insert superscript comma between adjacent footnotes
    text = re.sub(r'(</span>)\s*(<span class="nb-fn[ "])', r'\1<sup class="text-overlay0 text-[0.6em]">,</sup>\2', text)
    return text


def _resolve_node(name: str, node_index: dict) -> dict | None:
    if name in node_index:
        return node_index[name]
    for k, v in node_index.items():
        if k.endswith(f".{name}"):
            return v
    return None


# ── pltg syntax highlighting ──


def _highlight_pltg(code: str) -> str:
    escaped = html_mod.escape(code)
    for kw in [":origin", ":evidence", ":quotes", ":using", ":bind", ":with", ":explanation"]:
        escaped = escaped.replace(kw, f'<span class="text-peach">{kw}</span>')
    for d in ["fact", "axiom", "derive", "defterm", "diff", "import", "load-document"]:
        escaped = re.sub(rf"\(({d})\b", '(<span class="text-mauve">\\1</span>', escaped)
    escaped = re.sub(r'(&quot;[^&]*?&quot;)', r'<span class="text-green">\1</span>', escaped)
    escaped = re.sub(r'(;;.*?)$', r'<span class="text-overlay0 italic">\1</span>', escaped, flags=re.MULTILINE)
    return escaped


def _block_def_names(content: str) -> list[str]:
    """Extract definition names from a pltg block source."""
    return [m.group(2) for m in re.finditer(r'\((fact|axiom|derive|defterm|diff)\s+(\S+)', content)]


# ── Build notebook HTML from pgmd blocks ──


def _render_footnote_list(refs: list[dict]) -> str:
    """Render a compact footnote list below the prose section."""
    if not refs:
        return ""
    rows = []
    for r in refs:
        c = _KIND_COLORS.get(r["kind"], "subtext")
        val_html = f' = {html_mod.escape(r["value"])}' if r["value"] else ''
        rows.append(
            f'<div class="nb-fn-row flex items-center gap-1.5 py-0.5 cursor-pointer hover:bg-surface0 rounded px-1" '
            f'data-node="{html_mod.escape(r["node_id"])}" data-fn="{r["num"]}">'
            f'<span class="text-{c} text-[0.7em] font-mono w-4 text-right">{r["num"]}</span>'
            f'<span class="w-1.5 h-1.5 rounded-full bg-{c} shrink-0"></span>'
            f'<span class="text-{c} font-medium">{html_mod.escape(r["name"])}</span>'
            f'<span class="text-subtext">{val_html}</span>'
            f'</div>'
        )
    return '<div class="nb-footnote-list border-t border-surface1 mt-3 pt-2 text-xs">' + "\n".join(rows) + '</div>'


def _render_margin_pills(refs: list[dict]) -> str:
    """Render margin pills for a prose section's collected refs."""
    if not refs:
        return ""
    # Deduplicate by node_id, keep first occurrence (and its footnote num)
    seen: set[str] = set()
    unique: list[dict] = []
    for r in refs:
        if r["node_id"] not in seen:
            seen.add(r["node_id"])
            unique.append(r)
    pills = []
    for r in unique:
        c = _KIND_COLORS.get(r["kind"], "subtext")
        pills.append(
            f'<span class="nb-margin-pill inline-flex items-center gap-1 bg-surface0 '
            f'rounded-full px-2 py-0.5 text-[10px] cursor-pointer hover:bg-surface1 '
            f'transition-colors whitespace-nowrap" '
            f'data-node="{html_mod.escape(r["node_id"])}" data-fn="{r["num"]}">'
            f'<span class="text-overlay0 font-mono">{r["num"]}</span>'
            f'<span class="w-1.5 h-1.5 rounded-full bg-{c} shrink-0"></span>'
            f'<span class="text-{c} font-medium">{html_mod.escape(r["name"])}</span></span>'
        )
    return "\n".join(pills)


def build_notebook_html(
    blocks: list,  # list of PgmdBlock
    block_outputs: dict,  # {pltg_num: BlockOutput}
    node_index: dict,  # {name: item_dict}
    diagnostics: list[dict] | None = None,
    engine: Any = None,
) -> str:
    """Render pgmd blocks into notebook view HTML (goes inside #notebook-container)."""
    from parseltongue.core.inspect.notebooks.executor import BlockOutput

    global _footnote_counter
    _footnote_counter = 0

    sections: list[str] = []
    all_refs: list[dict] = []
    pltg_counter = 0

    for block in blocks:
        if block.kind == "prose":
            prose_html, refs = _md_to_html(block.content, node_index)
            all_refs.extend(refs)
            sections.append(prose_html)

        elif block.kind == "pltg":
            code_html = _highlight_pltg(block.content)
            title_text = block.title or f"Block {pltg_counter + 1}"

            output = block_outputs.get(pltg_counter, BlockOutput())
            stdout = (output.stdout or "").strip()
            stderr = (output.stderr or "").strip()
            error = output.error
            result = output.result

            # Output rows
            out_parts = []
            if result is not None:
                result_str = str(result)
                if len(result_str) > 500:
                    result_str = result_str[:497] + "..."
                out_parts.append(
                    f'<div class="border-t border-surface1 px-4 py-2 text-sm">'
                    f'<span class="text-overlay0 text-xs">Out:</span> '
                    f'<span class="text-lavender font-bold">{html_mod.escape(result_str)}</span></div>'
                )
            if stdout:
                out_parts.append(
                    f'<div class="border-t border-surface1 px-4 py-2 text-sm text-green whitespace-pre-wrap">{html_mod.escape(stdout)}</div>'
                )
            if stderr:
                out_parts.append(
                    f'<div class="border-t border-surface1 px-4 py-2 text-sm text-yellow whitespace-pre-wrap">{html_mod.escape(stderr)}</div>'
                )
            if error:
                out_parts.append(
                    f'<div class="border-t border-surface1 px-4 py-2 text-sm text-red whitespace-pre-wrap">{html_mod.escape(error)}</div>'
                )
            output_html = "\n".join(out_parts)

            has_error = bool(error or stderr)
            dot = "red" if has_error else "green"

            # Node pills: what this block produced
            pills: list[str] = []
            for bname in _block_def_names(block.content):
                node = _resolve_node(bname, node_index)
                if node:
                    c = _KIND_COLORS.get(node["kind"], "subtext")
                    val = _fmt_value(node["value"])
                    val_html = f' <span class="text-subtext">= {html_mod.escape(val)}</span>' if val else ''
                    pills.append(
                        f'<span class="nb-node-pill inline-flex items-center gap-1 bg-surface0 '
                        f'rounded-full px-2 py-0.5 text-xs cursor-pointer hover:bg-surface1" '
                        f'data-node="{html_mod.escape(node["id"])}">'
                        f'<span class="w-1.5 h-1.5 rounded-full bg-{c}"></span>'
                        f'<span class="text-{c}">{html_mod.escape(bname)}</span>{val_html}</span>'
                    )
            pills_row = ""
            if pills:
                pills_row = (
                    f'<div class="border-t border-surface1 px-4 py-2 flex flex-wrap gap-1.5">{"".join(pills)}</div>'
                )

            sections.append(f'''
<div class="my-5 border border-surface1 rounded-lg overflow-hidden bg-mantle" id="nb-block-{pltg_counter}">
  <div class="nb-block-header px-4 py-2 flex items-center gap-2 cursor-pointer select-none">
    <span class="w-2 h-2 rounded-full bg-{dot}"></span>
    <span class="text-mauve font-bold text-sm">pltg</span>
    <span class="text-subtext text-sm">{html_mod.escape(title_text)}</span>
    <span class="nb-arrow text-overlay0 text-xs ml-auto">&#9656;</span>
  </div>
  <pre class="nb-block-code bg-crust px-4 py-3 text-sm leading-relaxed overflow-x-auto hidden border-t border-surface1"><code>{code_html}</code></pre>
  {output_html}
  {pills_row}
</div>''')
            pltg_counter += 1

        elif block.kind == "code":
            sections.append(
                f'<pre class="bg-crust border border-surface1 rounded-lg p-4 my-4 text-sm overflow-x-auto">'
                f'<code>{html_mod.escape(block.content)}</code></pre>'
            )

    # Global footnote list at the bottom
    if all_refs:
        sections.append(_render_footnote_list(all_refs))

    # Diagnostics — grouped by severity, collapsible
    if diagnostics:
        by_sev: dict[str, list[dict]] = {}
        for d in diagnostics:
            by_sev.setdefault(d["severity"], []).append(d)

        n_err = len(by_sev.get("error", []))
        n_warn = len(by_sev.get("warning", []))
        n_info = len(by_sev.get("info", []))
        counts_parts = []
        if n_err:
            counts_parts.append(f'<span class="text-red">{n_err} errors</span>')
        if n_warn:
            counts_parts.append(f'<span class="text-yellow">{n_warn} warnings</span>')
        if n_info:
            counts_parts.append(f'<span class="text-subtext">{n_info} info</span>')
        counts_str = " &middot; ".join(counts_parts)

        sev_order = [("error", "red"), ("warning", "yellow"), ("info", "subtext")]
        groups_html = ""
        for sev_key, sev_color in sev_order:
            items_list = by_sev.get(sev_key, [])
            if not items_list:
                continue
            rows = "\n".join(
                f'<div class="px-4 py-1 border-t border-surface1 text-sm">' f'{html_mod.escape(d["message"])}</div>'
                for d in items_list
            )
            groups_html += f'''
<div class="border-t border-surface1">
  <div class="nb-block-header px-4 py-1.5 flex items-center gap-2 cursor-pointer select-none hover:bg-surface0">
    <span class="w-2 h-2 rounded-full bg-{sev_color}"></span>
    <span class="text-{sev_color} font-bold text-sm">{html_mod.escape(sev_key)}</span>
    <span class="text-overlay0 text-xs">{len(items_list)}</span>
    <span class="nb-arrow text-overlay0 text-xs ml-auto">&#9656;</span>
  </div>
  <div class="nb-block-code hidden max-h-64 overflow-y-auto">{rows}</div>
</div>'''

        sections.append(
            '<div class="mt-8 border border-surface1 rounded-lg overflow-hidden bg-mantle">'
            f'<div class="px-4 py-2 flex items-center gap-3">'
            f'<span class="text-mauve font-bold">Diagnostics</span>'
            f'<span class="text-xs">{counts_str}</span></div>' + groups_html + '</div>'
        )

    # System summary bar
    if engine is not None:
        nf = len(getattr(engine, "facts", {}) or {})
        nt = len(getattr(engine, "terms", {}) or {})
        na = len(getattr(engine, "axioms", {}) or {})
        nth = len(getattr(engine, "theorems", {}) or {})
        nd = len(diagnostics or [])
        health = f'<span class="text-red">{nd} issues</span>' if nd else '<span class="text-green">clean</span>'
        sections.append(f'''
<div class="mt-8 mb-4 p-4 bg-mantle rounded-lg text-sm flex items-center gap-4 flex-wrap border border-surface1">
  <span class="text-mauve font-bold">System</span>
  <span><span class="text-green">{nf}</span> facts</span>
  <span><span class="text-teal">{nt}</span> terms</span>
  <span><span class="text-peach">{na}</span> axioms</span>
  <span><span class="text-lavender">{nth}</span> theorems</span>
  <span class="ml-auto">{health}</span>
</div>''')

    return "\n".join(sections)


# ── Build items + layers from structure (shared logic) ──


def build_viz_data(structure: "CoreToConsequenceStructure") -> tuple[list[dict], dict, dict]:
    """Build (items, layers_data, node_index) from a probe structure.

    Returns:
        items: list of item dicts for DATA/STRUCTURE_DATA
        layers_data: dict with layers/edges for LAYERS
        node_index: {name: item_dict} for ref lookups
    """
    items: list[dict] = []
    for name, node in structure.graph.items():
        if name == "__output__":
            continue
        kind = node.kind.value if hasattr(node.kind, "value") else str(node.kind)
        from parseltongue.core.grammar import ParseltongueGrammar

        value_str = ParseltongueGrammar.enc(node.value)
        if len(value_str) > 200:
            value_str = value_str[:197] + "..."
        depth = structure.depths.get(name, 0)
        inputs = [str(i) for i in (node.inputs or [])]
        module = name.split(".")[0] if "." in name else ""
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

    node_index = {it["id"]: it for it in items}
    item_names = set(node_index)
    local = _localize_multi(_strip_internal(structure), item_names)
    layers_data = _build_layers_data(local)
    _enrich_items_from_structure(items, structure)

    # Rebuild index after enrichment (inputs may now be dicts)
    node_index = {it["id"]: it for it in items}
    return items, layers_data, node_index


# ── Assemble final HTML ──


def render_notebook(
    title: str,
    notebook_html: str,
    items: list[dict],
    layers_data: dict,
    structure_items: list[dict] | None = None,
) -> str:
    """Render the full notebook app HTML.

    Reads app.html, injects notebook tab + view + JS, substitutes data.
    Single source of truth — no template duplication.
    """
    base = _read("app.html")

    # 0. Inject notebook-specific CSS before </head>
    nb_css = """<style>
.nb-pill-active { outline: 2px solid var(--mauve); outline-offset: 1px; background: var(--surface1) !important; }
.nb-prose-row { position: relative; }
.nb-margin-notes {
  position: absolute; right: -200px; top: 0; width: 185px;
  display: flex; flex-direction: column; gap: 3px; align-items: flex-start;
}
.nb-margin-pill { line-height: 1.4; }
.nb-fn:hover sup { color: var(--mauve); }
#app { transition: margin-right 0.2s ease; }
#app.detail-open { margin-right: 420px; }
</style>
<script>
// After DOM ready, ensure prose rows are tall enough for their margin pills
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.nb-prose-row').forEach(function(row) {
    var notes = row.querySelector('.nb-margin-notes');
    if (!notes) return;
    var pillH = notes.scrollHeight;
    var contentH = row.querySelector(':not(.nb-margin-notes)').scrollHeight;
    if (pillH > contentH) {
      row.style.minHeight = pillH + 'px';
      row.style.marginBottom = Math.max(8, pillH - contentH + 4) + 'px';
    }
  });
});
</script>"""
    base = base.replace('</head>', nb_css + '\n</head>')

    # 1. Inject Notebook button before Source button
    base = base.replace(
        '<button id="btn-source"',
        '<button id="btn-notebook" class="px-3 py-1 rounded-lg text-xs bg-mauve text-crust font-bold">Notebook</button>\n'
        '        <button id="btn-source"',
    )
    # Source button starts inactive (notebook is default)
    base = base.replace(
        'id="btn-source" class="px-3 py-1 rounded-lg text-xs bg-mauve text-crust font-bold"',
        'id="btn-source" class="px-3 py-1 rounded-lg text-xs bg-surface0 text-subtext hover:bg-surface1"',
    )

    # 2. Inject Notebook view div before Source view
    notebook_view = (
        '  <!-- Notebook View -->\n'
        '  <div id="notebook-view" class="p-4 overflow-visible">\n'
        f'    <div id="notebook-container" class="max-w-[860px] mx-auto">{notebook_html}</div>\n'
        '  </div>\n\n'
    )
    base = base.replace('  <!-- Source View -->', notebook_view + '  <!-- Source View -->')

    # 3. Source view starts hidden (notebook is visible)
    base = base.replace(
        '<div id="source-view" class="p-4">',
        '<div id="source-view" class="hidden p-4">',
    )

    # 4. Change default init from renderSource() to switchView('notebook')
    #    (renderSource() is in app.html itself, not inside a JS template slot)
    base = base.replace('renderSource();', "switchView('notebook');")

    # 5. Read JS modules, patch core.js to include 'notebook' in VIEW_BTNS
    core_js = _read("core.js").replace(
        "const VIEW_BTNS = ['source', 'structure', 'layers', 'graph'];",
        "const VIEW_BTNS = ['notebook', 'source', 'structure', 'layers', 'graph'];",
    )

    # 6. Append notebook.js to layers.js (both are plain JS, no $ conflicts)
    notebook_js = _read("notebook.js")
    layers_js = _read("layers.js") + "\n\n" + notebook_js

    # 7. Substitute data via Template
    if structure_items is None:
        structure_items = items

    tmpl = Template(base)
    return tmpl.safe_substitute(
        title=_html_escape(title),
        data_json=json.dumps(items, separators=(",", ":")),
        structure_json=json.dumps(structure_items, separators=(",", ":")),
        layers_json=json.dumps(layers_data, separators=(",", ":")),
        form_type="ln",
        item_count=str(len(items)),
        core_js=core_js,
        source_js=_read("source.js"),
        cards_js=_read("cards.js"),
        detail_js=_read("detail.js"),
        graph_js=_read("graph.js"),
        layers_js=layers_js,
    )
