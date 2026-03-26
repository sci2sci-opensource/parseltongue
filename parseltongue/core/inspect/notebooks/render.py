"""Render a .pgmd notebook to self-contained HTML via bench.

Combines executor (bench pipeline) with notebook_renderer (viz integration).
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from parseltongue.core.inspect.perspectives.visualisation.notebook_renderer import (
    build_notebook_html,
    build_viz_data,
    render_notebook,
)

from .executor import NotebookResult, execute_pgmd


def render_pgmd(
    pgmd_path: str | Path,
    title: str | None = None,
    user: str | None = None,
    assistant: str | None = None,
) -> str:
    """Execute a .pgmd notebook and render to self-contained HTML.

    Args:
        pgmd_path: Path to the .pgmd file.
        title: Optional title. Defaults to filename stem.
        user: Optional user name for session booking.
        assistant: Optional assistant name for session booking.

    Returns:
        Complete HTML string with notebook view + viz app.
    """
    pgmd_path = Path(pgmd_path).resolve()
    if title is None:
        title = pgmd_path.stem.replace("_", " ").replace("-", " ").title()

    result = execute_pgmd(pgmd_path, user=user, assistant=assistant)
    return render_result(result, title)


def render_result(result: NotebookResult, title: str) -> str:
    """Render an already-executed NotebookResult to HTML."""
    items: list[dict] = []
    layers_data: dict = {"layers": [], "edges": []}
    node_index: dict = {}
    engine = None
    diagnostics: list[dict] = []

    bench = result.bench
    if bench is not None:
        try:
            lens = bench.lens()
            items, layers_data, node_index = build_viz_data(lens._structure)
        except Exception as e:
            print(f"Warning: lens failed: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

        try:
            engine = bench.engine
        except Exception:
            pass

        try:
            screen = bench.screen()
            for item in screen._items:
                sev = (
                    "error"
                    if item.category in ("issue", "loader")
                    else "warning" if item.category == "warning" else "info"
                )
                msg = f"[{item.type}] {item.name} @ {item.loc}"
                if item.detail and str(item.detail) != item.name:
                    msg += f"\n  {item.detail}"
                diagnostics.append({"severity": sev, "message": msg})
        except Exception as e:
            print(f"Warning: screen failed: {e}", file=sys.stderr)

    # Compute taints (shared with all viz views)
    from parseltongue.core.inspect.perspectives.visualisation.taints import compute_taints

    logbook = bench.logbook if bench is not None else []
    taint_result = compute_taints(
        items=items,
        edges=layers_data.get("edges", []),
        structure_items=items,
        logbook=logbook,
    )

    notebook_html = build_notebook_html(
        result.blocks, result.block_outputs, node_index, diagnostics, engine, taint_result=taint_result
    )
    return render_notebook(title, notebook_html, items, layers_data, logbook=logbook)
