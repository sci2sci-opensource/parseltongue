"""Shared Catppuccin Mocha (dark) + Latte (light) palette.

Single source of truth for colors used by:
  - pages/styles/theme.css  (generated palette block)
  - viz templates            (inline CSS variables)
"""

from __future__ import annotations

from collections import OrderedDict

# ── Font stacks ──

FONT_STACK = "system-ui, -apple-system, sans-serif"
MONO_STACK = "'JetBrains Mono', 'Fira Code', monospace"

# ── Shared palette (pages + viz) ──

PALETTE_DARK: OrderedDict[str, str] = OrderedDict(
    [
        ("base", "#1e1e2e"),
        ("mantle", "#181825"),
        ("crust", "#11111b"),
        ("surface0", "#313244"),
        ("surface1", "#45475a"),
        ("surface2", "#585b70"),
        ("overlay0", "#6c7086"),
        ("text", "#cdd6f4"),
        ("subtext", "#a6adc8"),
        ("green", "#a6e3a1"),
        ("red", "#f38ba8"),
        ("yellow", "#f9e2af"),
        ("blue", "#89b4fa"),
        ("mauve", "#cba6f7"),
        ("teal", "#94e2d5"),
        ("peach", "#fab387"),
        ("flamingo", "#f2cdcd"),
        ("sky", "#89dceb"),
        ("lavender", "#b4befe"),
        ("base-light", "#262637"),
        ("highlight", "rgba(250,204,21,0.30)"),
    ]
)

PALETTE_LIGHT: OrderedDict[str, str] = OrderedDict(
    [
        ("base", "#f9fafb"),
        ("mantle", "#ffffff"),
        ("crust", "#f3f4f6"),
        ("surface0", "#e5e7eb"),
        ("surface1", "#d1d5db"),
        ("surface2", "#9ca3af"),
        ("overlay0", "#6b7280"),
        ("text", "#111827"),
        ("subtext", "#4b5563"),
        ("green", "#16a34a"),
        ("red", "#dc2626"),
        ("yellow", "#ca8a04"),
        ("blue", "#2563eb"),
        ("mauve", "#7c3aed"),
        ("teal", "#0d9488"),
        ("peach", "#ea580c"),
        ("flamingo", "#e11d48"),
        ("sky", "#0284c7"),
        ("lavender", "#4f46e5"),
        ("base-light", "#f3f4f6"),
        ("highlight", "rgba(234,179,8,0.28)"),
    ]
)

# ── Viz-only extras (patronus glow, taint, warn) ──

VIZ_PALETTE_DARK: OrderedDict[str, str] = OrderedDict(
    [
        ("patronus", "#93b1e6"),
        ("patronus-core", "#abdaed"),
        ("patronus-glow", "#82c8e3"),
        ("patronus-glow-outer", "#58b5da"),
        ("patronus-highlight", "#d5edf6"),
        ("patronus-line", "#1c627d"),
        ("patronus-text-primary", "#d5edf6"),
        ("patronus-text-secondary", "#82c8e3"),
        ("patronus-text-muted", "#2ea3d1"),
        ("patronus-taint-core", "#c47a9a"),
        ("patronus-taint-glow", "#8a7ab5"),
        ("patronus-taint-outer", "#a07aaa"),
        ("patronus-warn-core", "#c8d94a"),
        ("patronus-warn-glow", "#b5c43e"),
        ("patronus-warn-outer", "#a0ad35"),
    ]
)

VIZ_PALETTE_LIGHT: OrderedDict[str, str] = OrderedDict(
    [
        ("patronus", "#4a72b0"),
        ("patronus-core", "#9ad4df"),
        ("patronus-glow", "#58b5da"),
        ("patronus-glow-outer", "#a4e1f9"),
        ("patronus-highlight", "#d4eaf2"),
        ("patronus-line", "#abdaed"),
        ("patronus-text-primary", "#6c9aac"),
        ("patronus-text-secondary", "#4e95b1"),
        ("patronus-text-muted", "#2582a7"),
        ("patronus-taint-core", "#b0607a"),
        ("patronus-taint-glow", "#7a5a95"),
        ("patronus-taint-outer", "#906a90"),
        ("patronus-warn-core", "#a8b82e"),
        ("patronus-warn-glow", "#95a528"),
        ("patronus-warn-outer", "#828f22"),
    ]
)


def _vars_line(palette: OrderedDict[str, str]) -> str:
    """Emit CSS custom properties as a compact semicolon-separated line."""
    return ";".join(f"--{k}:{v}" for k, v in palette.items()) + ";"


def css_variables(include_viz: bool = False) -> str:
    """Emit :root/[data-theme] CSS blocks for the Catppuccin palette.

    If *include_viz* is True, appends the patronus/taint/warn extras.
    """
    dark = OrderedDict(PALETTE_DARK)
    light = OrderedDict(PALETTE_LIGHT)
    if include_viz:
        dark.update(VIZ_PALETTE_DARK)
        light.update(VIZ_PALETTE_LIGHT)

    lines = [
        ':root, [data-theme="dark"] {',
        f"  {_vars_line(dark)}",
        "}",
        '[data-theme="light"] {',
        f"  {_vars_line(light)}",
        "}",
    ]
    return "\n".join(lines)


# ── Viz-only font override (no reset — Tailwind handles layout) ──

VIZ_TYPOGRAPHY = f"""\
body {{
  font-family: {FONT_STACK};
}}
code, pre {{
  font-family: {MONO_STACK};
  font-size: 0.9em;
}}
"""

# ── Full base typography for pages (includes reset + spacing) ──

BASE_TYPOGRAPHY = f"""\
/* ── Base ── */
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: {FONT_STACK};
  color: var(--text); background: var(--base);
  line-height: 1.6; min-height: 100vh;
  transition: background 0.2s, color 0.2s;
}}
a {{ color: var(--lavender); text-decoration: none; }}
a:hover {{ color: var(--mauve); }}
code, pre {{
  font-family: {MONO_STACK};
  font-size: 0.9em;
}}
code {{
  background: var(--surface0); padding: 0.15em 0.4em;
  border-radius: 4px;
}}
pre {{
  background: var(--mantle); padding: 1rem; border-radius: 8px;
  overflow-x: auto; border: 1px solid var(--surface0);
  position: relative;
}}
pre code {{ background: none; padding: 0; border: none; }}
[contenteditable],
[contenteditable] * {{
  outline: none !important;
  border-color: transparent !important;
  box-shadow: none !important;
  text-decoration: none !important;
  -webkit-tap-highlight-color: transparent;
  -webkit-focus-ring-color: transparent;
}}
[contenteditable] {{ caret-color: var(--text); }}

/* ── Typography ── */
h1 {{ font-size: 1.75rem; font-weight: 700; margin-bottom: 0.5rem; }}
h2 {{ font-size: 1.25rem; font-weight: 600; margin: 2rem 0 0.75rem; color: var(--lavender); }}
.subtitle {{ color: var(--subtext); font-size: 0.95rem; margin-bottom: 2rem; }}
.dim {{ color: var(--overlay0); font-size: 0.85rem; }}
"""
