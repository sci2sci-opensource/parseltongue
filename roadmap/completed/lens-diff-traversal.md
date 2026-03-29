# Lens Diff Traversal

**Branch**: plan/pgf

## Problem

The lens/probe system currently traverses facts, axioms, theorems, terms, and calcs — but not diffs. Diffs are the consistency layer: they compare two values and produce pass/fail. Currently only the screen (consistency) system evaluates diffs.

This means `pg-bench find`, `pg-bench view`, `pg-bench subgraph` etc. don't show diffs at all. Users must use `pg-bench screen` to see diff results.

## What we want

Diffs visible in the lens graph. A diff has two sides (:replace and :with) and a result (converge/diverge). Questions to resolve:

- **Representation**: How do diffs appear in CoreToConsequence? They consume definitions from both sides — they're natural "top layer" consumers.
- **Two-sided nature**: The dissect/hologram system already handles the two-sided view — could be a starting point for how to represent diffs in the probe structure.
- **Depth**: Diffs sit above everything they reference. They'd form the outermost layer(s).
- **Value**: The diff result (converge/diverge + actual values) is the natural node value.

## Result

Diffs are fully integrated into the lens/probe graph and visualization. `probe_diffs_to_possibilities()` in the Vital module walks both sides of every diff, augments with runtime edges via staining, and inserts DIFF nodes into the probe structure. Hologram dissection (`(dissect "diff-name")`) renders both sides as interactive HTML. `find` and `fuzzy` results containing diffs show inline hologram views. The viz detail panel displays diff convergence/divergence status with full evidence chains.

## Starting points

- `parseltongue/core/inspect/systems/hologram.py` — already probes both sides of a diff
- `parseltongue/core/inspect/probe_core_to_consequence.py` — the probe walker, would need to handle diff directives
- `parseltongue/core/inspect/screen.py` — where diffs are currently evaluated
