# Viz Graph v2 — Canvas+SVG Hybrid Graph Renderer

**Branch**: feature/viz-graph-v2
**PR**:

## Problem

The original graph view (v1) used a pure SVG D3 force layout. Every node and edge was an SVG element, which scaled poorly for large graphs (hundreds of nodes). Diff nodes with animated glow effects and regular nodes shared the same rendering path, making it hard to optimise either. Auto-fit zoom used `getBBox()` which included text overflow, and there was no viewport culling — all nodes rendered regardless of visibility.

Taint mode and focus/selection were mutually exclusive in v1: clicking a node in taint mode did nothing. The detail panel opening/closing didn't trigger header height recalculation, causing stats overlay misalignment when the app bar wrapped to two rows.

## What we want

- Canvas rendering for edges and overview nodes (cheap, scales to thousands)
- SVG for interactive nodes when zoomed in (clickable, hoverable, draggable)
- Permanent SVG diff nodes with animated glow (`<animate>`) at all zoom levels
- Viewport culling — only render what's visible
- Zoom-based label visibility (fade in between 0.35–0.7 zoom)
- Taint + focus coexistence — focus overlay on top of taint mode
- Auto-fit that matches v1's framing (uses `getBBox()` with temporary SVG nodes)
- User zoom respected — auto-fit skipped if user manually panned/zoomed
- Stats overlay correctly positioned when header wraps to 2 rows (detail panel open)
- v1 removed

## Proposal

### Architecture: canvas + SVG hybrid

Split nodes into `diffNodes` (always SVG) and `regularNodes` (canvas at overview, SVG when zoomed past `SVG_DETAIL_ZOOM = 0.5`). Edges always on canvas.

- **Canvas layer**: positioned absolute, pointer-events none. Draws edges and regular node dots when below SVG threshold.
- **SVG layer**: `gRoot` group with zoom transform. Contains permanent diff node `<g>` elements and dynamic regular node `<g>` elements (created/destroyed based on viewport).
- **Diff glow**: SVG `<animate>` on radius and opacity, matching v1's `patronus-pulse` keyframes. Paused (opacity → 0.08) when dimmed below alpha 0.1.

### Visual state functions

Unified `nodeAlpha()`, `nodeColor()`, `edgeAlpha()`, `edgeColor()`, `edgeLw()` compute visuals from combined taint+focus state:
- Both active: path nodes at full opacity, everything else at 0.05
- Focus only: path nodes bright, rest at 0.08
- Taint only: tainted nodes bright, rest at 0.15
- Neither: dangling at 0.5, rest at 1

### Key decisions

- Edge width in world-space (`ctx.lineWidth = lw`) so lines thin naturally on zoom out
- `userInteracted` flag set by `e.sourceEvent` in zoom handler — distinguishes manual zoom from programmatic transitions
- `_syncViewHeight()` called on detail panel open/close (220ms delay for CSS transition) to handle header reflow
- Auto-fit uses temporary SVG nodes + `getBBox()` for v1-consistent framing, then removes them
- `svg.on("click.zoom", null)` disables double-click zoom (matches v1)

### Taint system fix

`v.py` constants (`USER`, `ASSISTANT`) seeded as always-known participants in `default_predicate`, so `[Signed: V]` evidence is always clean regardless of logbook state.

## Files changed

- `visualisation/templates/graph_v2.js` — new canvas+SVG hybrid renderer (replaces graph.js as primary)
- `visualisation/templates/graph.js` — removed (original SVG-only renderer)
- `visualisation/templates/app.html` — graph view wires graph_v2.js, simplified theme toggle cleanup
- `visualisation/templates/detail.js` — `_syncViewHeight()` on panel open/close for header reflow
- `visualisation/renderer.py` — loads graph_v2.js instead of graph.js
- `visualisation/notebook_renderer.py` — loads graph_v2.js instead of graph.js
- `visualisation/taints.py` — seed known participants from `v.py` constants
- `pages/styles/pages.js` — unified theme localStorage key (`pltg-theme`) with viz/notebook pages
