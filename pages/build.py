#!/usr/bin/env python3
"""Build script for Parseltongue GitHub Pages.

Assembles _site/ from:
  - Static pages (index, quickstart, demos, construct) + styles
  - Rendered pgmd demos via `pg render`
  - Python demos wrapped in a Pyodide runner page
  - Rendered construct scenarios via `pg render`
  - Built wheel for Pyodide demos

Usage:
  python pages/build.py            # build into _site/
  python pages/build.py --clean    # rm _site/ first

Requires: parseltongue-dsl installed (for pg render CLI).
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from parseltongue.core.theme import BASE_TYPOGRAPHY, css_variables

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "pages"
SITE = ROOT / "_site"
DEMOS = ROOT / "parseltongue" / "core" / "demos"
CONSTRUCT = ROOT / "parseltongue" / "core" / "inspect" / "construct"
SCENARIOS = CONSTRUCT / "scenarios"

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


def copy_tree(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


# ── Static pages ──


def build_static():
    print("\n== Static pages ==")
    for f in ["index.html", "quickstart.html", "demos.html", "construct.html"]:
        src = PAGES / f
        dst = SITE / f
        shutil.copy2(src, dst)
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

    # Copy remaining style assets (pages.js, etc.)
    for f in (PAGES / "styles").iterdir():
        if f.name in ("theme.css", "theme_static.css"):
            continue
        shutil.copy2(f, styles_dst / f.name)
        print(f"  {f.name} -> {styles_dst / f.name}")

    # .nojekyll for GitHub Pages
    (SITE / ".nojekyll").touch()


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
                    "V",
                    "--assistant",
                    "Opus",
                    "-o",
                    str(dst),
                ],
                cwd=DEMOS / "ai2ai_pgmd",
            )
        except subprocess.CalledProcessError as e:
            print(f"  WARNING: render failed for {pgmd.name}: {e}")


# ── Python demos (Pyodide) ──

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
  /* Override Prism background to match theme */
  .file-panel pre[class*="language-"] {{ background: var(--mantle); }}
</style>
</head>
<body>
<div class="topnav">
  <a class="logo" href="../index.html">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -65.5 262 262" fill="currentColor"><path d="M65.5 0C29.4 0 0 29.4 0 65.5 0 101.6 29.4 131 65.5 131c27.4 0 38.6-14.2 51.5-32.8-3.8-6.2-1.5 1.2-4.7-4.7C93.6 107.6 87.9 112.3 65.5 112.3 39.7 112.3 18.7 91.3 18.7 65.5 18.7 39.5 39.5 18.7 65.5 18.7c15.1 0 24.7 5.4 33.6 14.6 8.9 9.2 16.4 22.5 24 36.5 7.6 14 15.3 28.8 26.6 40.6C161 122.4 176.6 131 196.5 131 232.6 131 262 101.6 262 65.5 262 29.4 232.6 0 196.5 0c-28.1 0-24.5 9.9-37.4 28.1 3.8 6.1-12.3 16.7-9.1 22.5C161.4 32.2 174.1 18.7 196.5 18.7c25.8 0 46.8 21 46.8 46.8 0 26-21.1 46.8-47 46.8-14.9 0-24.2-5.4-33-14.6-8.8-9.2-16.3-22.5-24-36.5-7.6-14-15.5-28.8-26.9-40.6C101.2 8.6 85.6 0 65.5 0Z"/><path d="M93.6 121.6c9.9-3.3 19.4-12.2 24.8-24.7 2.8-8 6.1-17.5-1.2-10-7.9 8.1-16 15-23.7 17.1v17.6Z"/><path d="M194.9 18.7V0c-12.5-.3-17.8 4.2-29 11.9-6.4 1.2-16.9-2.4-26.6 11.2-5.6 7.9-4.9 19.7-6 21.2-1 1.6-.4 10.2 10.9 9.3 11.2-.9 30.9-21 30.9-21 5.8-4.4 13.5-13.8 19.8-14Z"/></svg>
    parseltongue
  </a>
  <nav>
    <a href="../index.html">Home</a>
    <a href="../quickstart.html">Quickstart</a>
    <a href="../demos.html">Demos</a>
    <a href="../construct.html">Construct</a>
  </nav>
  <button id="theme-toggle" class="theme-toggle" onclick="toggleTheme()"></button>
</div>
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

// Tab key inserts 4 spaces in contenteditable
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

    // Write resource files into Pyodide FS at root
    for (var name in RESOURCES) {{
      var path = '/' + name;
      var parts = name.split('/');
      var dir = parts.slice(0, -1).join('/');
      if (dir) pyodide.runPython('import os; os.makedirs("/' + dir + '", exist_ok=True)');
      pyodide.FS.writeFile(path, RESOURCES[name]);
    }}

    // Write demo.py itself so __file__ resolves correctly
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
    import html as html_mod

    file_tabs_html = []
    file_panels_html = []
    for i, (fname, content, lang) in enumerate(all_files):
        fid = fname.replace("/", "_").replace(".", "_")
        active = " active" if i == 0 else ""
        file_tabs_html.append(
            f'    <button class="file-tab{active}" data-file="{fid}" '
            f'onclick="switchFile(\'{fid}\')">{html_mod.escape(fname)}</button>'
        )
        escaped = html_mod.escape(content)
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
        file_tabs="\n".join(file_tabs_html),
        file_panels="\n".join(file_panels_html),
        source_json=json.dumps(source),
        resources_json=json.dumps(resources),
        wheel_name=wheel_name,
    )

    dst = out / f"{name}.html"
    dst.write_text(page)
    print(f"  {name} -> {dst}")


def build_python_demos(wheel_path: Path | None):
    print("\n== Python demos (Pyodide) ==")
    out = SITE / "demos"
    out.mkdir(parents=True, exist_ok=True)

    wheel_name = wheel_path.name if wheel_path else "parseltongue_dsl-0.0.0-py3-none-any.whl"

    # Demos with demo.py (excluding pgmd-only and pltg-only that need loader)
    py_demos = [
        (
            "apples",
            "Apple Arithmetic",
            "Peano arithmetic from observational field notes about counting physical objects.",
        ),
        (
            "biomarkers",
            "Biomarker Evidence Conflict",
            "Two papers on fecal calprotectin with contradictory conclusions.",
        ),
        (
            "code_check",
            "Code Implementation Checks",
            "Facts extracted from a Python auth module, catching fabricated claims.",
        ),
        ("doc_validation", "Documentation Validation", "A library README with internally inconsistent claims."),
        ("extensibility", "System Extensibility", "Custom effects passed at construction time."),
        (
            "revenue_reports",
            "Revenue Reports",
            "Company performance analysis with quote verification and fabrication propagation.",
        ),
        ("self_healing", "Self-Healing Probes", "Entire flow in Parseltongue DSL with effects as an instruction set."),
        ("spec_validation", "Spec Cross-Validation", "API spec vs implementation divergences."),
    ]

    for name, title, description in py_demos:
        demo_dir = DEMOS / name
        demo_py = demo_dir / "demo.py"
        if not demo_py.exists():
            print(f"  WARNING: {demo_py} not found, skipping")
            continue

        # Read demo source
        source = demo_py.read_text()

        # Collect all viewable files: demo.py + resources + src
        all_files: list[tuple[str, str, str]] = []  # (display_name, content, lang)
        all_files.append(("demo.py", source, "python"))

        # Collect resource files from the entire demo directory
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

        _build_pyodide_page(out, name, title, description, source, all_files, resources, wheel_name)


# ── pltg demos (Pyodide — same as Python demos) ──


def build_pltg_demos(wheel_path: Path | None):
    print("\n== pltg demos (Pyodide) ==")
    out = SITE / "demos"
    out.mkdir(parents=True, exist_ok=True)

    wheel_name = wheel_path.name if wheel_path else "parseltongue_dsl-0.0.0-py3-none-any.whl"

    pltg_demos = [
        ("apples_pltg", "Apple Arithmetic (.pltg)", "Same orchard arithmetic loaded entirely through .pltg files."),
        ("apples_splats_pltg", "Apple Splats", "Variadic splat patterns for operations like (sum-all a b c d)."),
        (
            "data_governance_pltg",
            "Biopharma Data Governance",
            "Three-layer governance with cross-layer consistency checking.",
        ),
        ("deferred_pltg", "Deferred Directives", "run-on-entry blocks that only fire for the main file."),
        ("entry_mocks_pltg", "Entry Mocks", "Self-contained unit tests with let + mocks via run-on-entry."),
    ]

    for name, title, description in pltg_demos:
        demo_dir = DEMOS / name
        demo_py = demo_dir / "demo.py"
        if not demo_py.exists():
            print(f"  WARNING: {demo_py} not found, skipping")
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

        _build_pyodide_page(out, name, title, description, source, all_files, resources, wheel_name)


# ── Construct scenarios ──


def build_construct():
    print("\n== Construct scenarios ==")
    out = SITE / "construct"
    out.mkdir(parents=True, exist_ok=True)

    # White Rabbit is a .pg.md — render it
    wr = SCENARIOS / "INTRO_WHITE-RABBIT.pg.md"
    if wr.exists():
        dst = out / "white-rabbit.html"
        print(f"  rendering {wr.name} ...")
        try:
            run(
                [
                    "pg",
                    "render",
                    str(wr),
                    "--user",
                    "V",
                    "--assistant",
                    "Opus",
                    "-o",
                    str(dst),
                ],
                cwd=SCENARIOS,
            )
        except subprocess.CalledProcessError as e:
            print(f"  WARNING: render failed: {e}")
    else:
        print(f"  WARNING: {wr} not found")


# ── AI2AI pgmd demo page (index linking to sub-notebooks) ──


def build_ai2ai_index():
    """Create an index page for the ai2ai demo linking to rendered notebooks."""
    out = SITE / "demos"
    notebooks = sorted(out.glob("ai2ai_*.html"))
    if not notebooks:
        return

    import html as html_mod

    links = "\n".join(
        f'      <a class="card" href="{n.name}"><h3>{html_mod.escape(n.stem.replace("ai2ai_", "").replace("_", " ").title())}</h3></a>'
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
<div class="topnav">
  <a class="logo" href="../index.html">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -65.5 262 262" fill="currentColor"><path d="M65.5 0C29.4 0 0 29.4 0 65.5 0 101.6 29.4 131 65.5 131c27.4 0 38.6-14.2 51.5-32.8-3.8-6.2-1.5 1.2-4.7-4.7C93.6 107.6 87.9 112.3 65.5 112.3 39.7 112.3 18.7 91.3 18.7 65.5 18.7 39.5 39.5 18.7 65.5 18.7c15.1 0 24.7 5.4 33.6 14.6 8.9 9.2 16.4 22.5 24 36.5 7.6 14 15.3 28.8 26.6 40.6C161 122.4 176.6 131 196.5 131 232.6 131 262 101.6 262 65.5 262 29.4 232.6 0 196.5 0c-28.1 0-24.5 9.9-37.4 28.1 3.8 6.1-12.3 16.7-9.1 22.5C161.4 32.2 174.1 18.7 196.5 18.7c25.8 0 46.8 21 46.8 46.8 0 26-21.1 46.8-47 46.8-14.9 0-24.2-5.4-33-14.6-8.8-9.2-16.3-22.5-24-36.5-7.6-14-15.5-28.8-26.9-40.6C101.2 8.6 85.6 0 65.5 0Z"/><path d="M93.6 121.6c9.9-3.3 19.4-12.2 24.8-24.7 2.8-8 6.1-17.5-1.2-10-7.9 8.1-16 15-23.7 17.1v17.6Z"/><path d="M194.9 18.7V0c-12.5-.3-17.8 4.2-29 11.9-6.4 1.2-16.9-2.4-26.6 11.2-5.6 7.9-4.9 19.7-6 21.2-1 1.6-.4 10.2 10.9 9.3 11.2-.9 30.9-21 30.9-21 5.8-4.4 13.5-13.8 19.8-14Z"/></svg>
    parseltongue
  </a>
  <nav>
    <a href="../index.html">Home</a>
    <a href="../quickstart.html">Quickstart</a>
    <a href="../demos.html">Demos</a>
    <a href="../construct.html">Construct</a>
  </nav>
  <button id="theme-toggle" class="theme-toggle" onclick="toggleTheme()"></button>
</div>
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


# ── Main ──


def main():
    parser = argparse.ArgumentParser(description="Build Parseltongue pages")
    parser.add_argument("--clean", action="store_true", help="Remove _site/ first")
    args = parser.parse_args()

    if args.clean and SITE.exists():
        shutil.rmtree(SITE)
        print(f"Cleaned {SITE}")

    SITE.mkdir(parents=True, exist_ok=True)

    build_static()
    wheel = build_wheel()
    build_pgmd_demos()
    build_ai2ai_index()
    build_python_demos(wheel)
    build_pltg_demos(wheel)
    build_construct()

    print(f"\n== Done. Site at {SITE}/ ==")


if __name__ == "__main__":
    main()
