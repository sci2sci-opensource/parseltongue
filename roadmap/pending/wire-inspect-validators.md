# Wire the Inspect Validators — Close the Bench Blind Spot

## Problem

The bench is the largest unvalidated subsystem: ~50 modules under
`parseltongue/core/inspect/` carry zero quote evidence in the core
validation graph. Validators exist (`validation/inspect_bench.pltg`,
`inspect_search.pltg`, `inspect_lens.pltg`, `inspect_evaluate.pltg`,
`inspect_hologram.pltg`, orchestrated by `inspect_main.pltg`) but they
are outside `core_clean.pltg`'s import graph, and at least two of their
`load-document` paths point at files that no longer exist
(`inspect/searchable.py`, `inspect/diagnosis.py`), so `inspect_main`
does not even load strict.

This blind spot is not hypothetical: a recent stabilisation pass found
several real bench bugs (screen cache keyed without corpus state, reload
wiping the corpus, corpus verifier rooted at a file path, incremental
screens duplicating danglings) — all in exactly the code the validators
don't cover.

## What we want

- `inspect_*.pltg` load strict and clean: document paths repaired,
  stale quotes re-grounded against the current bench sources.
- The suite wired into a consistency entry point (either imported by
  `core_clean.pltg` or a second pytest gate loading `inspect_main.pltg`)
  so CI screens the bench like it screens the core.
- New ground truth for the invariants the recent bugs violated:
  screen cache key includes the corpus fingerprint, reload preserves
  the corpus, corpus verifier roots at the project root.

## Files likely involved

`parseltongue/core/validation/inspect_*.pltg`,
`parseltongue/core/validation/core_clean.pltg` or a new test in
`parseltongue/core/tests/`, bench sources under
`parseltongue/core/inspect/`.
