#!/usr/bin/env python3
"""Render all three AI2AI notebook patterns to HTML."""

import sys
from pathlib import Path

# Ensure project root is on path
project_root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(project_root))

from parseltongue.core.inspect.notebooks import render_pgmd  # noqa: E402

NOTEBOOKS = [
    ("notebooks/explicit.pgmd", "AI2AI — Explicit Pattern"),
    ("notebooks/implicit.pgmd", "AI2AI — Implicit Pattern"),
    ("notebooks/standalone.pgmd", "AI2AI — Standalone Pattern"),
]

demo_dir = Path(__file__).resolve().parent

OUTPUT_DIR = demo_dir / "pgmd_out"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

for rel_path, title in NOTEBOOKS:
    pgmd_path = demo_dir / rel_path
    stem = pgmd_path.stem
    print(f"Rendering {stem}...")
    try:
        html = render_pgmd(pgmd_path, title)
        out = OUTPUT_DIR / f"{stem}.html"
        out.write_text(html)
        print(f"  → {out} ({len(html):,} bytes)")
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)

print(f"\nDone. Output in {OUTPUT_DIR}/")
