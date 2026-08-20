# Coverage Reports as Part of the Consistency Check

## Problem

The typed coverage measures (`system.coverage()`: `quote_range` per
document, `corpus_claim` per file) are now sensible — the definition
graph is fully wired, dangling and alias measures are honest — but
coverage is only visible on demand (`pg screen --what coverage`, ad-hoc
scripts). Verification runs (the consistency pytest gate, CI
self-validation, screen summaries) say "consistent" without saying how
much of the corpus that consistency examined. A clean report over a
thin corpus reads stronger than it is.

## What we want

- The consistency surfaces report coverage alongside issues/warnings:
  the pytest gate prints an aggregate + per-document table, the CI
  consistency workflow surfaces it in the job summary, and the screen
  summary line includes the headline number.
- A trend guard, not a threshold theater: fail (or warn loudly) when
  aggregate quote coverage *drops* against a committed baseline, so
  refactors that orphan evidence get caught the way stale quotes are.
- Respect the layering already stated in `coverage.py`: core only
  measures; thresholds/grouping/display live in the consumers (test,
  CI, screen renderer).

## Approach

Baseline file (e.g. `validation/coverage_baseline.json` or facts inside
a `.pltg` so the baseline itself is part of the system) + a small
reporting helper consumed by the test and the screen. Extending
`--what coverage` output with aggregates is likely enough for the CLI.
