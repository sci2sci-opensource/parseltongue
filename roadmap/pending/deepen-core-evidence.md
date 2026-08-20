# Deepen Quote Evidence for the Evaluation Core

## Problem

Quote coverage (share of a registered document's text examined by
verified quotes) is thin exactly where the language semantics live.
Current measures over `core_clean.pltg`:

- `engines/engine_stack.py` — 3% (the actual evaluator: special-form
  handlers, rewriting, scopes, delegate/bind)
- `lang.py` — 8% (matcher, LANG_DOCS, keyword/directive vocabulary)
- `system.py` — 8%, `loader/loader_engine.py` — 2%, `core/__init__.py` — 7%
- healthy references for contrast: `quote_verifier/config.py` 42%,
  `default_system_settings.py` 38%, `verifier.py` / `ast.py` 31%

Whole areas also have no registered validation document at all:
`notebooks/` (15 modules), `search_engine/` (12), `integrity/`,
`serialization/`, `morphism.py`, `theme.py`. Aggregate over all
registered source documents: ~14% quoted.

## What we want

- Evidence for the evaluator's behavioral contracts in
  `engine_stack.py`: eval strategy (lazy `if`, strict, depth limit),
  scope/self/project/delegate semantics, rewrite fallback, retract /
  rederive — each as doc-vs-impl pairings, not decorative quotes.
- `lang.py` LANG_DOCS entries paired per form (the scope family got
  this recently; the older forms and keyword tables deserve the same
  depth).
- New validator modules for at least `search_engine/` and `integrity/`
  (the Merkle chain underwrites every cache decision — it should have
  ground truth).
- Re-measure with `system.coverage()`; targets are judgment calls per
  module, but the evaluator should not sit at 3%.

## Files likely involved

`validation/engine.pltg`, `validation/lang.pltg`, new
`validation/search_engine.pltg` / `validation/integrity.pltg`,
`validation/core_clean.pltg` imports.
