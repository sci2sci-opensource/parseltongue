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
    split_divergences,
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
    "diff": "patronus",
    "synthetic": "overlay0",
}


def _diff_state(node: dict) -> str:
    """Return 'coherent', 'tainted', or 'warn' for a diff node."""
    df = node.get("diff")
    if not df:
        return "coherent"
    if df.get("coherent"):
        cont = df.get("contaminated")
        return "warn" if cont and len(cont) > 0 else "coherent"
    return "tainted"


# Color-mixed patronus text hierarchy per diff state.
_DIFF_TEXT = {
    "coherent": ("var(--patronus-text-primary)", "var(--patronus-text-secondary)", "var(--patronus-text-muted)"),
    "tainted": ("var(--patronus-taint-core)", "var(--patronus-taint-glow)", "var(--patronus-taint-outer)"),
    "warn": ("var(--patronus-warn-core)", "var(--patronus-warn-glow)", "var(--patronus-warn-outer)"),
}


def _text_style(color: str, node: dict | None = None) -> str:
    """Return inline style for primary text color of a kind.

    Diff nodes use color-mixed patronus palette based on coherence state.
    """
    if color == "patronus":
        st = _diff_state(node) if node else "coherent"
        return f"color:{_DIFF_TEXT[st][0]}"
    return f"color:var(--{color})"


def _text_style_secondary(color: str, node: dict | None = None) -> str:
    if color == "patronus":
        st = _diff_state(node) if node else "coherent"
        return f"color:{_DIFF_TEXT[st][1]}"
    return f"color:var(--{color})"


def _text_style_muted(color: str, node: dict | None = None) -> str:
    if color == "patronus":
        st = _diff_state(node) if node else "coherent"
        return f"color:{_DIFF_TEXT[st][2]}"
    return "color:var(--overlay0)"


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
        av = abs(v)
        # Scientific notation for very small or very large values
        if v != 0 and (av < 1e-3 or av >= 1e12):
            return f"{v:.2e}"
        if v == int(v) and av >= 1_000_000:
            return f"{v / 1_000_000:.1f}M"
        if v == int(v) and av >= 1000:
            return f"{v:,.0f}"
        if 0 < av < 1:
            return f"{v:.2%}"
        if v == int(v):
            return str(int(v))
        return f"{v:.2f}"
    except (ValueError, OverflowError):
        if val_str in ("True", "true"):
            return "true"
        if val_str in ("False", "false"):
            return "false"
        # Strip surrounding quotes from strings
        if len(val_str) >= 2 and val_str[0] == '"' and val_str[-1] == '"':
            return val_str[1:-1]
        return val_str


# ── Markdown → HTML with footnote-style refs ──

# Global footnote state (reset per build_notebook_html call)
_footnote_counter: int = 0
_footnote_map: dict[str, int] = {}  # node_id → footnote number


def _wrap_with_margin(
    element_html: str,
    element_refs: list[dict],
    tainted: set[str] | None = None,
    taint_sources: set[str] | None = None,
    taint_reasons: dict[str, str] | None = None,
) -> str:
    """Wrap an HTML element with per-element margin pills if it introduced refs."""
    if not element_refs:
        return element_html
    pills = _render_margin_pills(
        element_refs, tainted=tainted, taint_sources=taint_sources, taint_reasons=taint_reasons
    )
    return (
        f'<div class="nb-prose-row relative">' f'{element_html}' f'<div class="nb-margin-notes">{pills}</div>' f'</div>'
    )


def _md_to_html(
    text: str,
    node_index: dict,
    tainted: set[str] | None = None,
    taint_sources: set[str] | None = None,
    taint_reasons: dict[str, str] | None = None,
) -> tuple[str, list[dict]]:
    """Convert markdown to HTML via AST, returning (html, collected_refs).

    Parses markdown into an AST first, then walks block tokens.
    Refs become inline footnotes; collected_refs is a list of
    {num, name, node_id, kind, value} dicts for margin pill rendering.
    Each block-level element gets its own margin pills aligned to it.
    """
    from parseltongue.core.notebooks.mdparser import parse_md_ast

    global _footnote_counter
    refs: list[dict] = []
    _t = tainted or set()
    _ts = taint_sources or set()
    _tr = taint_reasons or {}

    tokens = parse_md_ast(text)
    out = _render_blocks(tokens, node_index, refs, _t, _ts, _tr)
    return out, refs


# ── Heading level → CSS classes ──

_HEADING_CLASSES = {
    1: "text-2xl font-bold text-lavender mt-8 mb-4",
    2: "text-xl font-bold text-lavender mt-8 mb-3",
    3: "text-lg font-bold text-lavender mt-6 mb-2",
    4: "text-base font-bold text-lavender mt-4 mb-2",
    5: "text-sm font-bold text-lavender mt-3 mb-1",
    6: "text-sm font-bold text-lavender mt-3 mb-1",
}


def _render_blocks(
    tokens: list[dict],
    node_index: dict,
    refs: list[dict],
    _t: set[str],
    _ts: set[str],
    _tr: dict[str, str],
) -> str:
    """Walk a list of block-level AST tokens and return HTML."""
    parts: list[str] = []
    for tok in tokens:
        tt = tok["type"]

        if tt == "heading":
            before = len(refs)
            level = tok.get("attrs", {}).get("level", 1)
            cls = _HEADING_CLASSES.get(level, _HEADING_CLASSES[3])
            tag = f"h{level}"
            inner = _render_inline(tok.get("children", []), node_index, refs, _t, _ts)
            html = f'<{tag} class="{cls}">{inner}</{tag}>'
            parts.append(_wrap_with_margin(html, refs[before:], tainted=_t, taint_sources=_ts, taint_reasons=_tr))

        elif tt == "paragraph":
            before = len(refs)
            inner = _render_inline(tok.get("children", []), node_index, refs, _t, _ts)
            html = f'<p class="mb-3 leading-relaxed">{inner}</p>'
            parts.append(_wrap_with_margin(html, refs[before:], tainted=_t, taint_sources=_ts, taint_reasons=_tr))

        elif tt == "block_text":
            # tight list item content — no <p> wrapper, but still gets pills
            before = len(refs)
            inner = _render_inline(tok.get("children", []), node_index, refs, _t, _ts)
            parts.append(_wrap_with_margin(inner, refs[before:], tainted=_t, taint_sources=_ts, taint_reasons=_tr))

        elif tt == "list":
            ordered = tok.get("attrs", {}).get("ordered", False)
            if ordered:
                start = tok.get("attrs", {}).get("start", 1)
                start_attr = f' start="{start}"' if start != 1 else ""
                tag_open = f'<ol class="list-decimal ml-6 mb-4 space-y-1"{start_attr}>'
                tag_close = "</ol>"
            else:
                tag_open = '<ul class="list-disc ml-6 mb-4 space-y-1">'
                tag_close = "</ul>"
            items_html = []
            for child in tok.get("children", []):
                if child["type"] == "list_item":
                    li_inner = _render_blocks(child.get("children", []), node_index, refs, _t, _ts, _tr)
                    items_html.append(f"<li>{li_inner}</li>")
            html = tag_open + "\n" + "\n".join(items_html) + "\n" + tag_close
            parts.append(html)

        elif tt == "block_code":
            code = html_mod.escape(tok.get("raw", ""))
            info = (tok.get("attrs") or {}).get("info", "")
            lang_cls = f' class="language-{html_mod.escape(info)}"' if info else ""
            parts.append(
                f'<pre class="bg-crust border border-surface1 rounded-lg p-4 my-4 text-sm overflow-x-auto">'
                f"<code{lang_cls}>{code}</code></pre>"
            )

        elif tt == "block_quote":
            inner = _render_blocks(tok.get("children", []), node_index, refs, _t, _ts, _tr)
            parts.append(
                f'<blockquote class="border-l-4 border-surface1 pl-4 my-4 text-subtext italic">{inner}</blockquote>'
            )

        elif tt == "table":
            before = len(refs)
            html = _render_table(tok, node_index, refs, _t, _ts)
            parts.append(_wrap_with_margin(html, refs[before:], tainted=_t, taint_sources=_ts, taint_reasons=_tr))

        elif tt == "thematic_break":
            parts.append('<hr class="border-surface1 my-6">')

        elif tt == "block_html":
            parts.append(tok.get("raw", ""))

        elif tt == "blank_line":
            pass  # skip blank line tokens

        else:
            # Fallback: render children if present, otherwise raw
            if "children" in tok:
                parts.append(_render_blocks(tok["children"], node_index, refs, _t, _ts, _tr))
            elif "raw" in tok:
                parts.append(html_mod.escape(tok["raw"]))

    return "\n".join(parts)


def _render_table(
    tok: dict,
    node_index: dict,
    refs: list[dict],
    _t: set[str],
    _ts: set[str],
) -> str:
    """Render a table AST token to HTML."""
    parts = ['<table class="w-full border-collapse my-4 text-sm">']
    for section in tok.get("children", []):
        st = section["type"]
        if st == "table_head":
            parts.append("<thead>")
            parts.append("<tr>")
            for cell in section.get("children", []):
                align = (cell.get("attrs") or {}).get("align")
                style = f' style="text-align:{align}"' if align else ""
                inner = _render_inline(cell.get("children", []), node_index, refs, _t, _ts)
                parts.append(
                    f'<th class="border border-surface1 px-3 py-1.5 bg-surface0 text-left font-bold"{style}>{inner}</th>'
                )
            parts.append("</tr>")
            parts.append("</thead>")
        elif st == "table_body":
            parts.append("<tbody>")
            for row in section.get("children", []):
                parts.append("<tr>")
                for cell in row.get("children", []):
                    align = (cell.get("attrs") or {}).get("align")
                    style = f' style="text-align:{align}"' if align else ""
                    inner = _render_inline(cell.get("children", []), node_index, refs, _t, _ts)
                    parts.append(f'<td class="border border-surface1 px-3 py-1.5"{style}>{inner}</td>')
                parts.append("</tr>")
            parts.append("</tbody>")
    parts.append("</table>")
    return "\n".join(parts)


def _render_inline(
    tokens: list[dict],
    node_index: dict,
    refs: list[dict],
    _t: set[str],
    _ts: set[str],
) -> str:
    """Walk a list of inline AST tokens and return HTML string."""
    global _footnote_counter
    parts: list[str] = []
    for tok in tokens:
        tt = tok["type"]

        if tt == "text":
            parts.append(html_mod.escape(tok.get("raw", "")))

        elif tt == "strong":
            inner = _render_inline(tok.get("children", []), node_index, refs, _t, _ts)
            parts.append(f"<strong>{inner}</strong>")

        elif tt == "emphasis":
            inner = _render_inline(tok.get("children", []), node_index, refs, _t, _ts)
            parts.append(f"<em>{inner}</em>")

        elif tt == "codespan":
            code = html_mod.escape(tok.get("raw", ""))
            parts.append(f'<code class="bg-surface0 px-1.5 py-0.5 rounded text-peach text-sm">{code}</code>')

        elif tt == "link":
            url = html_mod.escape((tok.get("attrs") or {}).get("url", ""))
            title = (tok.get("attrs") or {}).get("title")
            title_attr = f' title="{html_mod.escape(title)}"' if title else ""
            inner = _render_inline(tok.get("children", []), node_index, refs, _t, _ts)
            parts.append(f'<a href="{url}" class="text-blue underline"{title_attr}>{inner}</a>')

        elif tt == "image":
            url = html_mod.escape((tok.get("attrs") or {}).get("url", ""))
            title = (tok.get("attrs") or {}).get("title")
            alt = ""
            for child in tok.get("children", []):
                if child.get("raw"):
                    alt = html_mod.escape(child["raw"])
            title_attr = f' title="{html_mod.escape(title)}"' if title else ""
            parts.append(f'<img src="{url}" alt="{alt}"{title_attr} class="max-w-full">')

        elif tt == "linebreak":
            parts.append("<br>")

        elif tt == "softbreak":
            parts.append("\n")

        elif tt == "inline_html":
            parts.append(tok.get("raw", ""))

        elif tt == "pgmd_ref":
            parts.append(_render_pgmd_ref(tok, node_index, refs, _t, _ts))

        else:
            # Fallback: children or raw
            if "children" in tok:
                parts.append(_render_inline(tok["children"], node_index, refs, _t, _ts))
            elif "raw" in tok:
                parts.append(html_mod.escape(tok["raw"]))

    result = "".join(parts)

    # Group adjacent footnotes into a single bracketed superscript [1, 2, 3].
    # Collect runs of adjacent nb-fn spans (allowing intervening closing tags).
    def _group_footnotes(m):
        return m.group(1) + m.group(2) + m.group(3)

    result = re.sub(
        r'(</span>)((?:</(?:strong|em|a)>)*)\s*(<span class="nb-fn[ "])',
        _group_footnotes,
        result,
    )
    return result


def _render_pgmd_ref(
    tok: dict,
    node_index: dict,
    refs: list[dict],
    _t: set[str],
    _ts: set[str],
) -> str:
    """Render a pgmd_ref inline token into an annotated footnote span."""
    global _footnote_counter
    attrs = tok.get("attrs", {})
    prefix = html_mod.escape(attrs.get("prefix", ""))
    suffix = html_mod.escape(attrs.get("suffix", ""))
    silent = attrs.get("silent", False)
    ref_type = attrs.get("ref_type", "")
    ref_name = attrs.get("ref_name", "")

    node = _resolve_node(ref_name, node_index)
    if not node:
        return f'{prefix}<span class="text-overlay0">{html_mod.escape(ref_type)}:{html_mod.escape(ref_name)}</span>{suffix}'

    node_id = node["id"]
    color = _KIND_COLORS.get(node["kind"], "subtext")
    val = _fmt_value(node["value"])
    is_tainted = node_id in _t
    is_source = node_id in _ts

    # Reuse footnote number for repeated refs to the same node
    if node_id in _footnote_map:
        fn_num = _footnote_map[node_id]
    else:
        _footnote_counter += 1
        fn_num = _footnote_counter
        _footnote_map[node_id] = fn_num

    refs.append(
        {
            "num": fn_num,
            "name": ref_name,
            "node_id": node_id,
            "kind": node["kind"],
            "value": val,
            "silent": silent,
            "tainted": is_tainted,
            "taint_source": is_source,
            "node": node,
        }
    )

    # Taint decoration — inside <sup> to stay aligned with footnote number
    taint_cls = ""
    taint_icon = ""
    if is_source:
        taint_cls = " nb-taint-source"
        taint_icon = '<span class="text-red ml-0.5" title="taint source">&#x2716;</span>'
    elif is_tainted:
        taint_cls = " nb-taint-propagated"
        taint_icon = '<span class="text-yellow ml-0.5" title="tainted">&#x26a0;</span>'

    esc_id = html_mod.escape(node_id)
    ts_pri = _text_style(color, node)
    ts_sec = _text_style_secondary(color, node)
    if silent:
        return (
            f'{prefix}<span class="nb-fn cursor-pointer{taint_cls}" '
            f'data-node="{esc_id}" data-fn="{fn_num}">'
            f'<sup class="text-[0.65em] font-bold" style="{ts_sec}">[{fn_num}{taint_icon}]</sup></span>{suffix}'
        )

    val_display = html_mod.escape(val) if val else html_mod.escape(ref_name)
    return (
        f'<span class="nb-fn font-semibold cursor-pointer '
        f'hover:underline decoration-dotted{taint_cls}" style="{ts_pri}" '
        f'data-node="{esc_id}" data-fn="{fn_num}">'
        f'{prefix}{val_display}{suffix}<sup class="text-[0.6em] ml-0.5" style="{ts_sec}">[{fn_num}{taint_icon}]</sup></span>'
    )


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
    """Render a compact footnote list below the prose section (deduplicated)."""
    if not refs:
        return ""
    seen: set[int] = set()
    rows = []
    for r in refs:
        if r["num"] in seen:
            continue
        seen.add(r["num"])
        c = _KIND_COLORS.get(r["kind"], "subtext")
        _node = r.get("node")
        ts_sec = _text_style_secondary(c, _node)
        ts_pri = _text_style(c, _node)
        val_html = f' = {html_mod.escape(r["value"])}' if r["value"] else ''
        rows.append(
            f'<div class="nb-fn-row flex items-center gap-1.5 py-0.5 cursor-pointer hover:bg-surface0 rounded px-1" '
            f'data-node="{html_mod.escape(r["node_id"])}" data-fn="{r["num"]}">'
            f'<span class="text-[0.7em] font-mono w-5 text-right" style="{ts_sec}">[{r["num"]}]</span>'
            f'<span class="w-1.5 h-1.5 rounded-full bg-{c} shrink-0"></span>'
            f'<span class="font-medium" style="{ts_pri}">{html_mod.escape(r["name"])}</span>'
            f'<span class="text-subtext">{val_html}</span>'
            f'</div>'
        )
    return '<div class="nb-footnote-list border-t border-surface1 mt-3 pt-2 text-xs">' + "\n".join(rows) + '</div>'


def _render_margin_pills(
    refs: list[dict],
    tainted: set[str] | None = None,
    taint_sources: set[str] | None = None,
    taint_reasons: dict[str, str] | None = None,
) -> str:
    """Render margin pills for a prose section's collected refs."""
    if not refs:
        return ""
    _t = tainted or set()
    _ts = taint_sources or set()
    _tr = taint_reasons or {}
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
        node_id = r["node_id"]
        is_source = node_id in _ts
        is_tainted = node_id in _t
        # Taint styling: dashed border + color change
        if is_source:
            border_cls = "border border-red"
            taint_icon = ' <span class="text-red">&#x2716;</span>'
            title = html_mod.escape(_tr.get(node_id, "taint source"))
        elif is_tainted:
            border_cls = "border border-dashed border-yellow"
            taint_icon = ' <span class="text-yellow">&#x26a0;</span>'
            title = html_mod.escape(_tr.get(node_id, "tainted"))
        else:
            border_cls = ""
            taint_icon = ""
            title = ""
        title_attr = f' title="{title}"' if title else ""
        _node = r.get("node")
        ts_mut = _text_style_muted(c, _node)
        ts_pri = _text_style(c, _node)
        pills.append(
            f'<span class="nb-margin-pill inline-flex items-center gap-1 bg-surface0 '
            f'rounded-full px-2 py-0.5 text-[10px] cursor-pointer hover:bg-surface1 '
            f'transition-colors whitespace-nowrap {border_cls}"{title_attr} '
            f'data-node="{html_mod.escape(node_id)}" data-fn="{r["num"]}">'
            f'<span class="font-mono" style="{ts_mut}">{r["num"]}</span>'
            f'<span class="w-1.5 h-1.5 rounded-full bg-{c} shrink-0"></span>'
            f'<span class="font-medium" style="{ts_pri}">{html_mod.escape(r["name"])}</span>{taint_icon}</span>'
        )
    return "\n".join(pills)


def build_notebook_html(
    blocks: list,  # list of PgmdBlock
    block_outputs: dict,  # {pltg_num: BlockOutput}
    node_index: dict,  # {name: item_dict}
    diagnostics: list[dict] | None = None,
    engine: Any = None,
    taint_result: Any = None,  # TaintResult from taints.py
) -> str:
    """Render pgmd blocks into notebook view HTML (goes inside #notebook-container)."""
    from parseltongue.core.inspect.notebooks.executor import BlockOutput

    global _footnote_counter, _footnote_map
    _footnote_counter = 0
    _footnote_map = {}

    # Build taint sets for pill styling
    taint_sources: set[str] = set(taint_result.sources) if taint_result else set()
    tainted: set[str] = set(taint_result.tainted) if taint_result else set()
    taint_reasons: dict[str, str] = dict(taint_result.reasons) if taint_result else {}

    sections: list[str] = []
    all_refs: list[dict] = []
    pltg_counter = 0

    for block in blocks:
        if block.kind == "prose":
            prose_html, refs = _md_to_html(
                block.content, node_index, tainted=tainted, taint_sources=taint_sources, taint_reasons=taint_reasons
            )
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
                # No truncation - show full output
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
                    node_id = node["id"]
                    is_source = node_id in taint_sources
                    is_tainted_node = node_id in tainted
                    if is_source:
                        pill_border = "border border-red"
                        taint_icon = ' <span class="text-red text-[0.7em]">&#x2716;</span>'
                    elif is_tainted_node:
                        pill_border = "border border-dashed border-yellow"
                        taint_icon = ' <span class="text-yellow text-[0.7em]">&#x26a0;</span>'
                    else:
                        pill_border = ""
                        taint_icon = ""
                    ts_pri = _text_style(c, node)
                    pills.append(
                        f'<span class="nb-node-pill inline-flex items-center gap-1 bg-surface0 '
                        f'rounded-full px-2 py-0.5 text-xs cursor-pointer hover:bg-surface1 {pill_border}" '
                        f'data-node="{html_mod.escape(node_id)}">'
                        f'<span class="w-1.5 h-1.5 rounded-full bg-{c} shrink-0"></span>'
                        f'<span class="font-medium" style="{ts_pri}">{html_mod.escape(bname)}</span>{val_html}{taint_icon}</span>'
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
        # No truncation - show full values
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


def merge_diff_structure(
    items: list[dict],
    layers_data: dict,
    node_index: dict,
    diff_structure: "CoreToConsequenceStructure",
) -> None:
    """Merge diff probe results into existing viz data (mutates in place).

    Adds new nodes from the diff structure (diff nodes and any upstream
    nodes not already present).  Existing nodes are left untouched —
    the lens structure is authoritative for those.
    """
    from parseltongue.core.grammar import ParseltongueGrammar

    if diff_structure is None or not diff_structure.graph:
        return

    existing_ids = set(node_index)
    new_items: list[dict] = []

    from parseltongue.core.inspect.probe_core_to_consequence import NodeKind

    for name, node in diff_structure.graph.items():
        if name == "__output__" or name in existing_ids:
            continue
        kind = node.kind.value if hasattr(node.kind, "value") else str(node.kind)
        depth = diff_structure.depths.get(name, 0)
        inputs = [str(i) for i in (node.inputs or [])]
        module = name.split(".")[0] if "." in name else ""

        # Diff nodes get structured value; others get encoded string
        if node.kind == NodeKind.DIFF and isinstance(node.value, dict):
            diff_val = node.value
            value_a = diff_val.get("value_a")
            value_b = diff_val.get("value_b")
            divergences = diff_val.get("divergences", {})
            real_divs, contaminated, has_real = split_divergences(divergences)
            coherent = value_a == value_b and not has_real
            va_s = _fmt_value(str(value_a)) if value_a is not None else "?"
            vb_s = _fmt_value(str(value_b)) if value_b is not None else "?"
            item_value = f"{va_s} = {vb_s}" if coherent else f"{va_s} \u2260 {vb_s}"
            diff_data = {
                "replace": diff_val.get("replace", ""),
                "with": diff_val.get("with", ""),
                "value_a": str(value_a) if value_a is not None else None,
                "value_b": str(value_b) if value_b is not None else None,
                "coherent": coherent,
                "divergences": real_divs,
                "contaminated": contaminated,
            }
        else:
            value_str = ParseltongueGrammar.enc(node.value)
            if len(value_str) > 200:
                value_str = value_str[:197] + "..."
            item_value = value_str
            diff_data = None

        item = {
            "id": name,
            "kind": kind,
            "value": item_value,
            "depth": depth,
            "inputs": inputs,
            "evidence": [],
            "module": module,
        }
        if diff_data is not None:
            item["diff"] = diff_data
        new_items.append(item)
        node_index[name] = item

    _enrich_items_from_structure(new_items, diff_structure)
    items.extend(new_items)

    # Merge layers and edges
    local = _localize_multi(_strip_internal(diff_structure), set(diff_structure.graph) - {"__output__"})
    diff_layers = _build_layers_data(local)

    existing_edge_keys = {f"{e['source']}>{e['target']}>{e['type']}" for e in layers_data.get("edges", [])}
    for edge in diff_layers.get("edges", []):
        key = f"{edge['source']}>{edge['target']}>{edge['type']}"
        if key not in existing_edge_keys:
            layers_data.setdefault("edges", []).append(edge)
            existing_edge_keys.add(key)

    existing_layer_nodes: dict[int, set[str]] = {}
    for ly in layers_data.get("layers", []):
        existing_layer_nodes[ly["depth"]] = {n["name"] for n in ly["nodes"]}

    for ly in diff_layers.get("layers", []):
        existing = existing_layer_nodes.get(ly["depth"])
        if existing is not None:
            target_layer = next(la for la in layers_data["layers"] if la["depth"] == ly["depth"])
            for n in ly["nodes"]:
                if n["name"] not in existing:
                    target_layer["nodes"].append(n)
                    existing.add(n["name"])
        else:
            layers_data.setdefault("layers", []).append(ly)
            existing_layer_nodes[ly["depth"]] = {n["name"] for n in ly["nodes"]}

    layers_data["layers"].sort(key=lambda ly: ly["depth"])


# ── Assemble final HTML ──


def render_notebook(
    title: str,
    notebook_html: str,
    items: list[dict],
    layers_data: dict,
    structure_items: list[dict] | None = None,
    logbook: list[dict] | None = None,
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
  display: flex; flex-wrap: wrap; gap: 4px 6px; align-items: center;
  margin-top: 6px; padding: 2px 0;
}
.nb-margin-pill { line-height: 1.4; }
.nb-fn:hover sup { color: var(--mauve); }
.nb-fn.nb-fn-active sup { color: var(--lavender); }
.nb-row-highlight { background: var(--highlight); border-radius: 6px; transition: background 0.3s; }
.nb-node-pill.nb-pill-active { outline: 2px solid var(--mauve); outline-offset: 1px; background: var(--surface1) !important; }
.nb-taint-source { text-decoration: underline wavy var(--red); text-underline-offset: 3px; }
.nb-taint-propagated { text-decoration: underline dashed var(--yellow); text-underline-offset: 3px; }
#app { transition: margin-right 0.2s ease; }
#app.detail-open { margin-right: min(420px, 35vw); }

/* Wide screens: margin notes float to the right using available space */
@media (min-width: 1100px) {
  .nb-margin-notes {
    position: absolute; right: 0; top: 0;
    transform: translateX(calc(100% + 16px));
    width: calc((100vw - min(860px, 90vw)) / 2 - 40px);
    max-width: 280px; min-width: 120px;
    margin-top: 0;
  }
  .detail-open .nb-margin-notes {
    width: calc((100vw - min(860px, 90vw) - min(420px, 35vw)) / 2 - 40px);
  }
}
</style>
<script>
// After DOM ready, ensure prose rows are tall enough for their margin pills
document.addEventListener('DOMContentLoaded', function() {
  if (window.innerWidth < 1100) return; // only needed for absolute-positioned pills
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
        f'    <div id="notebook-container" class="max-w-[min(860px,90vw)] mx-auto">{notebook_html}</div>\n'
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

    # Compute taints
    from .taints import compute_taints

    taint_result = compute_taints(
        items=structure_items,
        edges=layers_data.get("edges", []),
        structure_items=structure_items,
        logbook=logbook,
    )

    from parseltongue.core.theme import VIZ_TYPOGRAPHY, css_variables

    tmpl = Template(base)
    return tmpl.safe_substitute(
        palette_css=css_variables(include_viz=True),
        base_css=VIZ_TYPOGRAPHY,
        title=_html_escape(title),
        data_json=json.dumps(items, separators=(",", ":")),
        structure_json=json.dumps(structure_items, separators=(",", ":")),
        layers_json=json.dumps(layers_data, separators=(",", ":")),
        taint_json=json.dumps(taint_result.to_json(), separators=(",", ":")),
        form_type="ln",
        item_count=str(len(items)),
        core_js=core_js,
        source_js=_read("source.js"),
        cards_js=_read("cards.js"),
        detail_js=_read("detail.js"),
        graph_js=_read("graph.js"),
        layers_js=layers_js,
    )
