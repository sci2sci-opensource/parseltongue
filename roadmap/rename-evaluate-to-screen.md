# Rename Evaluate to Screen

## Problem

The current name `evaluate` / `Evaluation` is overloaded — the engine also has `evaluate()` for S-expression evaluation. The health check operation is conceptually a screening: run the sample through checks, report what's healthy and what's not.

## What needs to happen

Rename across the codebase:
- `bench.evaluate()` -> `bench.screen()`
- `Evaluation` class -> `Screen` (or `Screening`)
- `EvaluationItem` -> `ScreenItem`
- `EvaluationSearchSystem` -> `ScreenSearchSystem`
- `_evaluation_mem` -> `_screen_mem`
- `_load_evaluate` -> `_load_screen`
- Scope name `"evaluation"` -> `"screen"`
- CLI `pg-bench diagnose` — consider renaming to `pg-bench screen`
- All test references

## Scope

Mechanical rename. No logic changes. Should be done in one pass with thorough grep to catch all references.
