# Viz Health Overlay

## Problem

The viz UI shows structural data (probe: evidence, quotes, file locations) but not health data (evaluation: issues, fabrications, divergences). A node like `no-phantoms-ok` can evaluate to `false` (potential fabrication) while the viz shows perfectly green evidence — the user has no signal that anything is wrong.

Taint mode shows which nodes differ structurally between diff sides, but doesn't surface whether a derive's evaluated value is correct or fabricated.

## What needs to happen

### 1. VizRenderer receives evaluation

`VizRenderer.__init__` gets an optional `evaluation: Evaluation` parameter alongside the existing `structure`.

**Files**: `renderer.py`

### 2. Technician passes evaluation when creating renderers

In `_register_scopes`, the evaluation is already computed (`dx`). Pass it to both the frozen and live VizRenderer instances.

**Files**: `technician.py` lines ~156-193

### 3. Build health index in `_render_app`

When evaluation is available, build a `name -> list[EvaluationItem]` lookup. For each item in DATA/STRUCTURE_DATA, attach a `health` field:

```json
{
  "health": [
    {"category": "issue", "type": "potential_fabrication", "detail": "no-phantoms-ok"},
    {"category": "issue", "type": "diff_value_divergence", "detail": "..."}
  ]
}
```

Include issues, warnings, and loader errors. Skip danglings (noise).

**Files**: `renderer.py` — `_extract_hn_items`, `_extract_ln_items`, `_build_named_structure_data`

### 4. JS detail panel renders health

When an item has a non-empty `health` array, the detail panel shows a health section:
- Red for issues (fabrication, divergence, unverified evidence)
- Yellow for warnings
- Gray for loader errors

Show the type and detail text. This goes above or below the existing evidence section so the user sees both: "evidence says X" and "but health check says Y."

**Files**: `templates/detail.js`

### 5. Graph/card visual indicators

Nodes with health issues get a visual marker (border color, dot, badge) so they stand out without clicking. This makes health problems visible at a glance in both card and graph views.

**Files**: `templates/cards.js`, `templates/graph.js`

## Issue types to surface

| Type | Category | Meaning |
|------|----------|---------|
| `potential_fabrication` | issue | Derive evaluated to unexpected value |
| `diff_value_divergence` | issue | Diff sides don't match |
| `unverified_evidence` | issue | Quoted evidence doesn't match document |
| `error` | loader | Directive failed to load (missing effects, etc.) |
| `skipped` | loader | Cascading skip from upstream error |

## Test case

Data governance demo with corruptions:
- `no-phantoms-ok` should show `potential_fabrication` in detail panel
- `all-omics-ok` should show fabrication when omics contracts are weakened
- `policy-check` should show `diff_value_divergence`
- Nodes with issues should be visually distinct from healthy nodes

## Shipped

Health landed as a first-class viz view rather than only per-node
markers: HEALTH_DATA/COVERAGE_DATA side-cars next to TAINT_DATA, a
detail-panel Health section, red/yellow card and graph markers, a
full-page diagnostics view (verdict, stat tiles, coverage chart,
findings and documents columns), and a typed search bar —
diag:<facet> filters structurally by finding type/category. Notebook
pages ship the same real side-cars. Test case: the engine overview
notebook, which surfaced the core spec's real drift (661 issues).
