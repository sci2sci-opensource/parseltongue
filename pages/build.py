#!/usr/bin/env python3
"""Build script for Parseltongue GitHub Pages.

Assembles _site/ from:
  - Static pages (index, quickstart) + styles
  - Generated pages (demos, construct) from filesystem discovery
  - Rendered pgmd demos via `pg render`
  - Python/pltg demos wrapped in a Pyodide runner page
  - Rendered construct scenarios via `pg render`
  - Built wheel for Pyodide demos

Usage:
  python pages/build.py            # build into _site/
  python pages/build.py --clean    # rm _site/ first

Requires: parseltongue-dsl installed (for pg render CLI).
"""

import argparse
import ast
import html as html_mod
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from parseltongue.core.theme import BASE_TYPOGRAPHY, css_variables
from parseltongue.core.v import ASSISTANT, USER

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
SITE = ROOT / "_site"
DEMOS = ROOT / "parseltongue" / "core" / "demos"
CONSTRUCT = ROOT / "parseltongue" / "core" / "inspect" / "construct"

# ── Shared HTML fragments ──

_FAVICON = (
    '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,'
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 -65.5 262 262'%3E"
    "%3Cpath d='M65.5 0C29.4 0 0 29.4 0 65.5 0 101.6 29.4 131 65.5 131c27.4 0 38.6-14.2 51.5-32.8-3.8-6.2-1.5 1.2-4.7-4.7C93.6 107.6 87.9 112.3 65.5 112.3 39.7 112.3 18.7 91.3 18.7 65.5 18.7 39.5 39.5 18.7 65.5 18.7c15.1 0 24.7 5.4 33.6 14.6 8.9 9.2 16.4 22.5 24 36.5 7.6 14 15.3 28.8 26.6 40.6C161 122.4 176.6 131 196.5 131 232.6 131 262 101.6 262 65.5 262 29.4 232.6 0 196.5 0c-28.1 0-24.5 9.9-37.4 28.1 3.8 6.1-12.3 16.7-9.1 22.5C161.4 32.2 174.1 18.7 196.5 18.7c25.8 0 46.8 21 46.8 46.8 0 26-21.1 46.8-47 46.8-14.9 0-24.2-5.4-33-14.6-8.8-9.2-16.3-22.5-24-36.5-7.6-14-15.5-28.8-26.9-40.6C101.2 8.6 85.6 0 65.5 0Z' fill='%23b4befe'/%3E"
    "%3Cpath d='M93.6 121.6c9.9-3.3 19.4-12.2 24.8-24.7 2.8-8 6.1-17.5-1.2-10-7.9 8.1-16 15-23.7 17.1v17.6Z' fill='%23b4befe'/%3E"
    "%3Cpath d='M194.9 18.7V0c-12.5-.3-17.8 4.2-29 11.9-6.4 1.2-16.9-2.4-26.6 11.2-5.6 7.9-4.9 19.7-6 21.2-1 1.6-.4 10.2 10.9 9.3 11.2-.9 30.9-21 30.9-21 5.8-4.4 13.5-13.8 19.8-14Z' fill='%23b4befe'/%3E"
    "%3C/svg%3E\">"
)

_LOGO_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -65.5 262 262" fill="currentColor"><path d="M65.5 0C29.4 0 0 29.4 0 65.5 0 101.6 29.4 131 65.5 131c27.4 0 38.6-14.2 51.5-32.8-3.8-6.2-1.5 1.2-4.7-4.7C93.6 107.6 87.9 112.3 65.5 112.3 39.7 112.3 18.7 91.3 18.7 65.5 18.7 39.5 39.5 18.7 65.5 18.7c15.1 0 24.7 5.4 33.6 14.6 8.9 9.2 16.4 22.5 24 36.5 7.6 14 15.3 28.8 26.6 40.6C161 122.4 176.6 131 196.5 131 232.6 131 262 101.6 262 65.5 262 29.4 232.6 0 196.5 0c-28.1 0-24.5 9.9-37.4 28.1 3.8 6.1-12.3 16.7-9.1 22.5C161.4 32.2 174.1 18.7 196.5 18.7c25.8 0 46.8 21 46.8 46.8 0 26-21.1 46.8-47 46.8-14.9 0-24.2-5.4-33-14.6-8.8-9.2-16.3-22.5-24-36.5-7.6-14-15.5-28.8-26.9-40.6C101.2 8.6 85.6 0 65.5 0Z"/><path d="M93.6 121.6c9.9-3.3 19.4-12.2 24.8-24.7 2.8-8 6.1-17.5-1.2-10-7.9 8.1-16 15-23.7 17.1v17.6Z"/><path d="M194.9 18.7V0c-12.5-.3-17.8 4.2-29 11.9-6.4 1.2-16.9-2.4-26.6 11.2-5.6 7.9-4.9 19.7-6 21.2-1 1.6-.4 10.2 10.9 9.3 11.2-.9 30.9-21 30.9-21 5.8-4.4 13.5-13.8 19.8-14Z"/></svg>'


def _topnav(active: str, prefix: str = "") -> str:
    """Generate topnav HTML. active is one of: index, quickstart, demos, construct."""
    links = [
        ("index.html", "Home", "index"),
        ("quickstart.html", "Quickstart", "quickstart"),
        ("demos.html", "Demos", "demos"),
        ("construct.html", "Construct", "construct"),
    ]
    nav_items = "\n    ".join(
        f'<a href="{prefix}{href}"{" class=\"active\"" if key == active else ""}>{label}</a>'
        for href, label, key in links
    )
    return f"""<div class="topnav">
  <a class="logo" href="{prefix}index.html">
    {_LOGO_SVG}
    parseltongue
  </a>
  <nav>
    {nav_items}
  </nav>
  <button id="theme-toggle" class="theme-toggle" onclick="toggleTheme()"></button>
</div>"""


# ── Helpers ──


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


_SKIP_DIRS = {"__pycache__", ".parseltongue-bench", "temp", "viz-results"}
_SKIP_SUFFIXES = {".pyc", ".html", ".pgz", ".DS_Store"}


def _should_skip(rel_str: str, suffix: str) -> bool:
    """Skip generated/cache files in demo directories."""
    parts = rel_str.split("/")
    if any(p.startswith(".") or p in _SKIP_DIRS for p in parts):
        return True
    return suffix in _SKIP_SUFFIXES


def _esc(s: str) -> str:
    return html_mod.escape(s)


# ── Demo discovery ──


def _demo_docstring(demo_dir: Path) -> tuple[str, str] | None:
    """Extract (title, description) from demo.py module docstring."""
    demo_py = demo_dir / "demo.py"
    if not demo_py.exists():
        return None
    try:
        tree = ast.parse(demo_py.read_text())
    except SyntaxError:
        return None
    doc = ast.get_docstring(tree)
    if not doc:
        return None

    lines = doc.strip().splitlines()
    title = ""
    desc_lines: list[str] = []
    in_desc = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Demo:"):
            title = stripped.removeprefix("Demo:").strip().rstrip(".")
        elif not in_desc and stripped and not stripped.startswith("Demo"):
            # First non-title, non-empty line starts the description
            in_desc = True
            if stripped.startswith("Scenario:"):
                stripped = stripped.removeprefix("Scenario:").strip()
            desc_lines.append(stripped)
        elif in_desc and stripped:
            desc_lines.append(stripped)
        elif in_desc and not stripped:
            break

    if not title:
        title = demo_dir.name.replace("_", " ").title()

    return title, " ".join(desc_lines)


def _demo_kind(name: str) -> str:
    """Detect demo kind from directory name: pgmd, pltg, or py."""
    if name.endswith("_pgmd"):
        return "pgmd"
    if name.endswith("_pltg"):
        return "pltg"
    return "py"


def discover_demos() -> list[dict]:
    """Discover all demos from the filesystem."""
    demos: list[dict] = []
    if not DEMOS.exists():
        return demos

    # ai2ai_pgmd is special — no demo.py, rendered via pg render
    ai2ai = DEMOS / "ai2ai_pgmd"
    if ai2ai.exists():
        demos.append(
            {
                "name": "ai2ai_pgmd",
                "title": "AI2AI Investment Memo",
                "description": (
                    "Three notebook patterns — standalone, explicit, implicit — "
                    "analyzing a Series A investment memo. Shows facts with verified "
                    "quotes, cross-document derivation, and taint tracking."
                ),
                "kind": "pgmd",
                "dir": ai2ai,
            }
        )

    for d in sorted(DEMOS.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if d.name == "ai2ai_pgmd":
            continue  # handled above
        info = _demo_docstring(d)
        if info is None:
            continue
        title, description = info
        demos.append(
            {
                "name": d.name,
                "title": title,
                "description": description,
                "kind": _demo_kind(d.name),
                "dir": d,
            }
        )
    return demos


# ── Static pages ──


def _read_pyproject() -> dict[str, str]:
    """Read version and release_tagline from pyproject.toml."""
    import tomllib

    with open(ROOT / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    proj = data.get("project", {})
    tool_pt = data.get("tool", {}).get("parseltongue", {})
    return {
        "version": proj.get("version", "0.0.0"),
        "release_tagline": tool_pt.get("release_tagline", ""),
    }


def build_static():
    print("\n== Static pages ==")
    meta = _read_pyproject()

    for name in ["index.html", "quickstart.html"]:
        src = PAGES / name
        dst = SITE / name
        content = src.read_text()
        if name == "index.html":
            content = content.replace("$version", meta["version"])
            content = content.replace("$release_tagline", meta["release_tagline"])
        dst.write_text(content)
        print(f"  {src.name} -> {dst}")

    # Generate theme.css from shared theme module + pages-only static styles
    styles_dst = SITE / "styles"
    styles_dst.mkdir(parents=True, exist_ok=True)

    pages_static = (PAGES / "styles" / "theme_static.css").read_text()
    theme_css = (
        "/* Generated from parseltongue.core.theme — do not edit by hand. */\n\n"
        + css_variables()
        + "\n\n"
        + BASE_TYPOGRAPHY
        + "\n"
        + pages_static
    )
    (styles_dst / "theme.css").write_text(theme_css)
    print(f"  theme.css (generated) -> {styles_dst / 'theme.css'}")

    for p in (PAGES / "styles").iterdir():
        if p.name in ("theme.css", "theme_static.css"):
            continue
        shutil.copy2(p, styles_dst / p.name)
        print(f"  {p.name} -> {styles_dst / p.name}")

    (SITE / ".nojekyll").touch()


# ── Generated: demos.html ──


def build_demos_page(demos: list[dict]):
    """Generate demos.html from discovered demos."""
    print("\n== demos.html (generated) ==")

    cards = []
    for d in demos:
        kind = d["kind"]
        href = f"demos/{d['name']}.html"
        if d["name"] == "ai2ai_pgmd":
            href = "demos/ai2ai_pgmd.html"
        cards.append(
            f'      <a class="card" href="{href}" data-kind="{kind}">\n'
            f'        <h3><span class="badge badge-{kind}">{kind}</span> {_esc(d["title"])}</h3>\n'
            f'        <p>{_esc(d["description"])}</p>\n'
            f'      </a>'
        )

    all_cards = "\n".join(cards)

    page = f"""\
<!DOCTYPE html>
<html data-theme="dark" lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {_FAVICON}
  <title>Demos - Parseltongue</title>
  <link rel="stylesheet" href="styles/theme.css">
</head>
<body>

{_topnav("demos")}

<div class="page-wide">
  <h1>Demos</h1>
  <p class="subtitle">Worked examples showing Parseltongue in action. Each demo is a self-contained project.</p>

  <div class="tab-bar">
    <button class="tab-btn active" data-tab-group="dtype" data-tab="all" onclick="switchTab('dtype','all')">All</button>
    <button class="tab-btn" data-tab-group="dtype" data-tab="pgmd" onclick="switchTab('dtype','pgmd')"><span class="badge badge-pgmd">pgmd</span></button>
    <button class="tab-btn" data-tab-group="dtype" data-tab="pltg" onclick="switchTab('dtype','pltg')"><span class="badge badge-pltg">pltg</span></button>
    <button class="tab-btn" data-tab-group="dtype" data-tab="py" onclick="switchTab('dtype','py')"><span class="badge badge-py">py</span></button>
  </div>

  <div class="tab-panel active" data-panel-group="dtype" data-panel="all">
    <div class="card-grid">
{all_cards}
    </div>
  </div>

  <div class="tab-panel" data-panel-group="dtype" data-panel="pgmd">
    <div class="card-grid" id="pgmd-cards"></div>
  </div>
  <div class="tab-panel" data-panel-group="dtype" data-panel="pltg">
    <div class="card-grid" id="pltg-cards"></div>
  </div>
  <div class="tab-panel" data-panel-group="dtype" data-panel="py">
    <div class="card-grid" id="py-cards"></div>
  </div>
</div>

<script src="styles/pages.js"></script>
<script>
['pgmd','pltg','py'].forEach(function(kind) {{
  var target = document.getElementById(kind + '-cards');
  document.querySelectorAll('[data-panel="all"] [data-kind="' + kind + '"]').forEach(function(card) {{
    target.appendChild(card.cloneNode(true));
  }});
}});
</script>
</body>
</html>
"""
    (SITE / "demos.html").write_text(page)
    print(f"  demos.html -> {SITE / 'demos.html'}")


# ── Generated: construct.html ──


def build_construct_page():
    """Generate construct.html from TOPICS registry."""
    print("\n== construct.html (generated) ==")
    from parseltongue.core.inspect.construct import TOPICS

    rows = []
    for slug, topic in TOPICS.items():
        desc = _esc(topic["description"])
        has_script = "script" in topic
        has_scenario = "scenario" in topic

        script_cell = (
            f'<a href="construct/{slug}.html"><span class="status-ready">ready</span></a>'
            if has_script
            else '<span class="status-todo">&ndash;</span>'
        )
        scenario_cell = (
            f'<a href="construct/{slug}.html"><span class="status-ready">ready</span></a>'
            if has_scenario
            else '<span class="status-todo">&ndash;</span>'
        )

        if has_scenario:
            rows.append(
                f'      <tr class="clickable" onclick="location.href=\'construct/{slug}.html\'">\n'
                f'        <td class="name">{_esc(slug)}</td>\n'
                f'        <td class="desc">{desc}</td>\n'
                f'        <td>{script_cell}</td>\n'
                f'        <td>{scenario_cell}</td>\n'
                f'      </tr>'
            )
        else:
            rows.append(
                f'      <tr>\n'
                f'        <td class="name">{_esc(slug)}</td>\n'
                f'        <td class="desc">{desc}</td>\n'
                f'        <td>{script_cell}</td>\n'
                f'        <td>{scenario_cell}</td>\n'
                f'      </tr>'
            )

    table_rows = "\n".join(rows)

    page = f"""\
<!DOCTYPE html>
<html data-theme="dark" lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {_FAVICON}
  <title>Construct - Parseltongue</title>
  <link rel="stylesheet" href="styles/theme.css">
  <style>
    .construct-table {{ width: 100%; border-collapse: collapse; margin: 1.5rem 0; }}
    .construct-table th {{
      text-align: left; padding: 0.6rem 0.75rem; font-size: 0.8rem;
      color: var(--overlay0); border-bottom: 1px solid var(--surface0);
      font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
    }}
    .construct-table td {{
      padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--surface0);
      font-size: 0.9rem; vertical-align: top;
    }}
    .construct-table tr:hover td {{ background: var(--surface0); }}
    .construct-table tr.clickable {{ cursor: pointer; }}
    .construct-table tr.clickable:hover td {{ background: var(--surface1); }}
    .construct-table .name {{ color: var(--lavender); font-weight: 600; white-space: nowrap; }}
    .construct-table .desc {{ color: var(--subtext); }}
    .status-ready {{
      display: inline-block; padding: 0.1em 0.45em; border-radius: 4px;
      font-size: 0.75rem; font-weight: 600;
      background: var(--green); color: var(--crust);
    }}
    .status-todo {{
      display: inline-block; padding: 0.1em 0.45em; border-radius: 4px;
      font-size: 0.75rem; font-weight: 600;
      background: var(--surface1); color: var(--overlay0);
    }}
    .modes {{ margin: 1.5rem 0; }}
    .modes h3 {{ font-size: 1rem; margin-bottom: 0.35rem; }}
    .modes p {{ font-size: 0.9rem; color: var(--subtext); margin-bottom: 1rem; }}
  </style>
</head>
<body>

{_topnav("construct")}

<div class="page">
  <h1>Construct</h1>
  <p class="subtitle">The place where both agents and humans learn Parseltongue.</p>

  <blockquote style="border-left: 3px solid var(--mauve); padding-left: 1rem; margin: 1.5rem 0; color: var(--subtext); font-style: italic;">"I know kung fu."</blockquote>

  <div class="modes">
    <h3>Two modes, mirrored</h3>
    <p><strong>Scripts</strong> are for agents. An LLM loads a script with <code>pg learn &lt;name&gt;</code> and gains operational knowledge &mdash; these are the guides available via the CLI and in the repository.</p>
    <p><strong>Scenarios</strong> are for humans. Interactive notebooks that build understanding of what Parseltongue is, how to work with it, and how to keep LLM agents accountable during collaborative sessions.</p>
  </div>

  <h2>Topics</h2>

  <table class="construct-table">
    <thead>
      <tr>
        <th>Name</th>
        <th>Description</th>
        <th>Script</th>
        <th>Scenario</th>
      </tr>
    </thead>
    <tbody>
{table_rows}
    </tbody>
  </table>

  <h2>Start here</h2>
  <p>If you're a human, read <a href="construct/white-rabbit.html"><strong>Follow the White Rabbit</strong></a>. It explains what Parseltongue is, why LLMs lying is an engineering problem, and walks through the system from first principles &mdash; with live parseltongue blocks running inside the document itself.</p>
  <p>If you're steering an agent, tell it:</p>
  <div class="prompt"><p>Run <code>pg learn kung-fu</code> and read the full output. This is your operational guide for the Parseltongue bench system.</p></div>
  <p>Then enjoy the show of an LLM bumping into Parseltongue guardrails. You would be surprised how illusory intelligence can appear once it needs to be proven explicitly.</p>
</div>

<script src="styles/pages.js"></script>
</body>
</html>
"""
    (SITE / "construct.html").write_text(page)
    print(f"  construct.html -> {SITE / 'construct.html'}")


# ── Wheel ──


def build_wheel() -> Path | None:
    print("\n== Build wheel ==")
    dist = ROOT / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    try:
        run([sys.executable, "-m", "build", "--wheel", str(ROOT)], cwd=ROOT)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  WARNING: wheel build failed ({e}), skipping Pyodide assets")
        return None

    wheels = list(dist.glob("*.whl"))
    if not wheels:
        print("  WARNING: no wheel found in dist/")
        return None

    whl = wheels[0]
    assets = SITE / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    dst = assets / whl.name
    shutil.copy2(whl, dst)
    print(f"  {whl.name} -> {dst}")
    return dst


# ── pgmd demos ──


def build_pgmd_demos():
    print("\n== pgmd demos ==")
    out = SITE / "demos"
    out.mkdir(parents=True, exist_ok=True)

    ai2ai = DEMOS / "ai2ai_pgmd" / "notebooks"
    if not ai2ai.exists():
        print("  WARNING: ai2ai_pgmd/notebooks not found, skipping")
        return

    for pgmd in sorted(ai2ai.glob("*.pgmd")):
        stem = pgmd.stem
        dst = out / f"ai2ai_{stem}.html"
        print(f"  rendering {pgmd.name} ...")
        try:
            run(
                [
                    "pg",
                    "render",
                    str(pgmd),
                    "--user",
                    USER,
                    "--assistant",
                    ASSISTANT,
                    "-o",
                    str(dst),
                ],
                cwd=DEMOS / "ai2ai_pgmd",
            )
        except subprocess.CalledProcessError as e:
            print(f"  WARNING: render failed for {pgmd.name}: {e}")


# ── Pyodide demos (py + pltg — auto-discovered) ──

PYODIDE_TEMPLATE = """\
<!DOCTYPE html>
<html data-theme="dark" lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - Parseltongue Demo</title>
<link rel="stylesheet" href="../styles/theme.css">
<style>
  .demo-output {{
    background: var(--mantle); border: 1px solid var(--surface0);
    border-radius: 8px; padding: 1rem; min-height: 200px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.85rem; white-space: pre-wrap; overflow-x: auto;
    color: var(--green);
  }}
  .demo-output.error {{ color: var(--red); }}
  .run-btn {{
    background: var(--green); color: var(--crust); border: none;
    padding: 0.5rem 1.5rem; border-radius: 6px; cursor: pointer;
    font-weight: 600; font-size: 0.9rem; font-family: inherit;
    transition: background 0.15s; margin-bottom: 0.75rem;
  }}
  .run-btn:hover {{ background: var(--teal); }}
  .run-btn:disabled {{ background: var(--surface1); color: var(--overlay0); cursor: wait; }}
  .loading {{ color: var(--yellow); }}
  .editable-code {{ outline: none; cursor: text; }}
  .editable-code:focus {{ box-shadow: inset 0 0 0 1px var(--lavender); }}
  .reset-btn {{
    background: var(--surface0); color: var(--subtext); border: none;
    padding: 0.35rem 0.75rem; border-radius: 6px; cursor: pointer;
    font-size: 0.8rem; font-family: inherit; margin-left: 0.5rem;
    transition: background 0.15s, color 0.15s;
  }}
  .reset-btn:hover {{ background: var(--surface1); color: var(--text); }}
  .file-tabs {{ display: flex; gap: 0.25rem; margin-bottom: 0; overflow-x: auto; flex-shrink: 0; }}
  .file-tab {{
    padding: 0.4rem 0.75rem; border-radius: 6px 6px 0 0; border: none;
    background: var(--surface0); color: var(--subtext);
    font-size: 0.8rem; cursor: pointer; font-family: 'JetBrains Mono', monospace;
    transition: background 0.15s, color 0.15s; white-space: nowrap; flex-shrink: 0;
  }}
  .file-tab:hover {{ background: var(--surface1); color: var(--text); }}
  .file-tab.active {{ background: var(--mantle); color: var(--lavender); font-weight: 600;
    border: 1px solid var(--surface0); border-bottom-color: var(--mantle); }}
  .file-panel {{ display: none; }}
  .file-panel.active {{ display: block; }}
  .file-panel pre {{ border-radius: 0 8px 8px 8px; margin-top: 0; max-height: 500px; overflow-y: auto; }}
  .file-panel pre code {{ font-size: 0.82rem; }}
  .file-panel pre[class*="language-"] {{ background: var(--mantle); }}
</style>
</head>
<body>
{topnav}
<div class="page-wide">
  <h1>{title}</h1>
  <p class="subtitle">{description}</p>

  <h2>Files</h2>
  <div class="file-tabs">
{file_tabs}
  </div>
{file_panels}

  <h2 style="margin-top:2rem;">Output</h2>
  <button class="run-btn" id="run-btn" onclick="runDemo()">Run in browser</button>
  <button class="reset-btn" onclick="resetSource()">Reset source</button>
  <div class="demo-output" id="output"><span class="loading">Click "Run in browser" to execute this demo with Pyodide.</span></div>
</div>

<script src="../styles/pages.js"></script>
<script src="https://cdn.jsdelivr.net/npm/prismjs@1.29.0/prism.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/prismjs@1.29.0/components/prism-python.min.js"></script>
<script>
var WHEEL_NAME = "{wheel_name}";
var RESOURCES = {resources_json};
var DEMO_SOURCE = {source_json};

function switchFile(id) {{
  document.querySelectorAll('.file-tab').forEach(function(t) {{ t.classList.toggle('active', t.dataset.file === id); }});
  document.querySelectorAll('.file-panel').forEach(function(p) {{ p.classList.toggle('active', p.dataset.file === id); }});
}}

function resetSource() {{
  var ed = document.getElementById('demo-editor');
  if (ed) {{ ed.textContent = DEMO_SOURCE; Prism.highlightElement(ed); }}
}}

document.addEventListener('DOMContentLoaded', function() {{
  var ed = document.getElementById('demo-editor');
  if (!ed) return;
  ed.addEventListener('keydown', function(e) {{
    if (e.key === 'Tab') {{
      e.preventDefault();
      var sel = window.getSelection();
      var range = sel.getRangeAt(0);
      var space = document.createTextNode('    ');
      range.deleteContents();
      range.insertNode(space);
      range.setStartAfter(space);
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
    }}
  }});
}});

async function runDemo() {{
  var btn = document.getElementById('run-btn');
  var out = document.getElementById('output');
  var ed = document.getElementById('demo-editor');
  var source = ed ? ed.textContent : DEMO_SOURCE;
  btn.disabled = true;
  out.className = 'demo-output';
  out.textContent = 'Loading Pyodide...\\n';

  try {{
    var pyodide = await loadPyodide();
    out.textContent += 'Installing Parseltongue...\\n';
    await pyodide.loadPackage('micropip');
    var micropip = pyodide.pyimport('micropip');
    var wheelUrl = new URL('../assets/' + WHEEL_NAME, window.location.href).href;
    await micropip.install(wheelUrl);

    for (var name in RESOURCES) {{
      var path = '/' + name;
      var parts = name.split('/');
      var dir = parts.slice(0, -1).join('/');
      if (dir) pyodide.runPython('import os; os.makedirs("/' + dir + '", exist_ok=True)');
      pyodide.FS.writeFile(path, RESOURCES[name]);
    }}

    pyodide.FS.writeFile('/demo.py', source);
    out.textContent += 'Running demo...\\n\\n';

    pyodide.setStdout({{ batched: function(s) {{ out.textContent += s + '\\n'; }} }});
    pyodide.setStderr({{ batched: function(s) {{ out.textContent += s + '\\n'; }} }});

    pyodide.runPython('import sys; sys.path.insert(0, "/")\\n__file__ = "/demo.py"\\n' + source);
  }} catch (e) {{
    out.textContent += '\\nERROR: ' + e.message;
    out.className = 'demo-output error';
  }}
  btn.disabled = false;
}}
</script>
<script src="https://cdn.jsdelivr.net/pyodide/v0.27.0/full/pyodide.js"></script>
</body>
</html>
"""


def _build_pyodide_page(
    out: Path,
    name: str,
    title: str,
    description: str,
    source: str,
    all_files: list[tuple[str, str, str]],
    resources: dict[str, str],
    wheel_name: str,
):
    file_tabs_html = []
    file_panels_html = []
    for i, (fname, content, lang) in enumerate(all_files):
        fid = fname.replace("/", "_").replace(".", "_")
        active = " active" if i == 0 else ""
        file_tabs_html.append(
            f'    <button class="file-tab{active}" data-file="{fid}" '
            f'onclick="switchFile(\'{fid}\')">{_esc(fname)}</button>'
        )
        escaped = _esc(content)
        if fname == "demo.py":
            file_panels_html.append(
                f'  <div class="file-panel{active}" data-file="{fid}">'
                f'<pre><code id="demo-editor" class="language-{lang} editable-code" '
                f'contenteditable="true" spellcheck="false">{escaped}</code></pre></div>'
            )
        else:
            file_panels_html.append(
                f'  <div class="file-panel{active}" data-file="{fid}">'
                f'<pre><code class="language-{lang}">{escaped}</code></pre></div>'
            )

    page = PYODIDE_TEMPLATE.format(
        title=title,
        description=description,
        topnav=_topnav("demos", prefix="../"),
        file_tabs="\n".join(file_tabs_html),
        file_panels="\n".join(file_panels_html),
        source_json=json.dumps(source),
        resources_json=json.dumps(resources),
        wheel_name=wheel_name,
    )

    dst = out / f"{name}.html"
    dst.write_text(page)
    print(f"  {name} -> {dst}")


def build_pyodide_demos(demos: list[dict], wheel_path: Path | None):
    """Build Pyodide runner pages for all py and pltg demos."""
    print("\n== Pyodide demos (auto-discovered) ==")
    out = SITE / "demos"
    out.mkdir(parents=True, exist_ok=True)

    wheel_name = wheel_path.name if wheel_path else "parseltongue_dsl-0.0.0-py3-none-any.whl"

    for d in demos:
        if d["kind"] == "pgmd":
            continue

        demo_dir = d["dir"]
        demo_py = demo_dir / "demo.py"
        if not demo_py.exists():
            continue

        source = demo_py.read_text()
        all_files: list[tuple[str, str, str]] = [("demo.py", source, "python")]
        resources: dict[str, str] = {}

        for f in sorted(demo_dir.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(demo_dir)
            rel_str = str(rel)
            if rel_str == "demo.py" or _should_skip(rel_str, f.suffix):
                continue
            try:
                content = f.read_text()
                resources[rel_str] = content
                ext = f.suffix
                lang = {
                    ".py": "python",
                    ".pltg": "scheme",
                    ".txt": "text",
                    ".md": "markdown",
                    ".json": "json",
                    ".csv": "text",
                }.get(ext, "text")
                all_files.append((rel_str, content, lang))
            except UnicodeDecodeError:
                print(f"  WARNING: skipping binary resource {rel}")

        _build_pyodide_page(
            out,
            d["name"],
            d["title"],
            d["description"],
            source,
            all_files,
            resources,
            wheel_name,
        )


# ── AI2AI pgmd demo page ──


def build_ai2ai_index():
    """Create an index page for the ai2ai demo linking to rendered notebooks."""
    out = SITE / "demos"
    notebooks = sorted(out.glob("ai2ai_*.html"))
    if not notebooks:
        return

    links = "\n".join(
        f'      <a class="card" href="{n.name}"><h3>'
        f'{_esc(n.stem.replace("ai2ai_", "").replace("_", " ").title())}</h3></a>'
        for n in notebooks
    )

    page = f"""\
<!DOCTYPE html>
<html data-theme="dark" lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI2AI Investment Memo - Parseltongue Demo</title>
<link rel="stylesheet" href="../styles/theme.css">
</head>
<body>
{_topnav("demos", prefix="../")}
<div class="page">
  <h1>AI2AI Investment Memo</h1>
  <p class="subtitle">Three notebook patterns analyzing a Series A investment memo.</p>
  <div class="card-grid">
{links}
  </div>
</div>
<script src="../styles/pages.js"></script>
</body>
</html>
"""
    dst = out / "ai2ai_pgmd.html"
    dst.write_text(page)
    print(f"  ai2ai index -> {dst}")


# ── Construct: scripts + scenarios ──


def build_construct_content():
    """Render all discovered scripts and scenarios to construct/ HTML pages."""
    print("\n== Construct content ==")
    from parseltongue.core.inspect.construct import SCENARIOS as SCENARIO_MAP
    from parseltongue.core.inspect.construct import SCRIPTS as SCRIPT_MAP

    out = SITE / "construct"
    out.mkdir(parents=True, exist_ok=True)

    # Scripts (.md files — render via pg render)
    scripts_dir = CONSTRUCT / "scripts"
    for slug, (filename, _desc) in SCRIPT_MAP.items():
        src = scripts_dir / filename
        if not src.exists():
            print(f"  WARNING: {src} not found, skipping")
            continue
        dst = out / f"{slug}.html"
        print(f"  script {filename} -> {slug}.html ...")
        try:
            run(
                [
                    "pg",
                    "render",
                    str(src),
                    "--user",
                    USER,
                    "--assistant",
                    ASSISTANT,
                    "-o",
                    str(dst),
                ],
                cwd=scripts_dir,
            )
        except subprocess.CalledProcessError as e:
            print(f"  WARNING: render failed for {filename}: {e}")

    # Scenarios (.pg.md / .pgmd / .md files)
    scenarios_dir = CONSTRUCT / "scenarios"
    for slug, (filename, _desc) in SCENARIO_MAP.items():
        src = scenarios_dir / filename
        if not src.exists():
            print(f"  WARNING: {src} not found, skipping")
            continue
        dst = out / f"{slug}.html"
        print(f"  scenario {filename} -> {slug}.html ...")
        try:
            run(
                [
                    "pg",
                    "render",
                    str(src),
                    "--user",
                    USER,
                    "--assistant",
                    ASSISTANT,
                    "-o",
                    str(dst),
                ],
                cwd=scenarios_dir,
            )
        except subprocess.CalledProcessError as e:
            print(f"  WARNING: render failed for {filename}: {e}")


# ── Main ──


def main():
    parser = argparse.ArgumentParser(description="Build Parseltongue pages")
    parser.add_argument("--clean", action="store_true", help="Remove _site/ first")
    args = parser.parse_args()

    if args.clean and SITE.exists():
        shutil.rmtree(SITE)
        print(f"Cleaned {SITE}")

    SITE.mkdir(parents=True, exist_ok=True)

    demos = discover_demos()
    print(f"\nDiscovered {len(demos)} demos: {', '.join(d['name'] for d in demos)}")

    build_static()
    build_demos_page(demos)
    build_construct_page()
    wheel = build_wheel()
    build_pgmd_demos()
    build_ai2ai_index()
    build_pyodide_demos(demos, wheel)
    build_construct_content()

    print(f"\n== Done. Site at {SITE}/ ==")


if __name__ == "__main__":
    main()
