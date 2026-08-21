# Core Consistency Test — Stabilisation Phase

**Branch**: feature/core-consistency-stabilisation

## Problem

`test_parseltongue_core_consistency.py` currently fails. The core .pltg files need significant updates to pass the consistency check. This is known technical debt.

## Status

Done. The core .pltg coverage was built incrementally and has accumulated inconsistencies (stale evidence quotes, dangling counts, unfilled stub sides of diffs, etc.). Fixing this requires a focused pass through all core .pltg files to align facts, evidence, and derives with the current codebase state.

## What's needed

- Audit all core .pltg files for stale quotes, missing diffs, dangling definitions
- Update evidence quotes to match current source code
- Add missing diffs for derives that lack them
- Verify all fact values match reality
- Get `python -m pytest parseltongue/core/tests/test_parseltongue_core_consistency.py -q` to pass clean

## Proposal

Screen-driven stabilisation via the repo bench (`pg screen` on
`validation/core_clean.pltg`), one category at a time, re-screening after
each pass. Current baseline: 2 loader errors, 375 issues
(127 unverified_evidence, 120 potential_fabrication, 109 no_evidence,
19 diff_value_divergence), 121 danglings.

1. **Loader errors** — dedupe the duplicate directive names in
   `engine.pltg` (`error-layers-consistent`, `warning-layers-consistent`).
2. **Unverified evidence** — re-quote all stale evidence blocks against the
   current source files. This also clears the bulk of
   `potential_fabrication`, which is a downstream taint of unverified
   sources.
3. **Stub TODOs** — stubs whose feature has since landed become real
   grounded facts with paired diffs; stubs for genuinely unlanded work stay
   explicit.
4. **Diff divergences** — align README-vs-implementation counts and fill
   the `util.stub` sides of `thm-*` diffs.
5. **Danglings / no-evidence std imports** — wire into derives or sign via
   `verify-manual` where import-only.
6. Drop the `xfail` markers in `test_parseltongue_core_consistency.py`
   category by category as each reaches zero; the test passing clean closes
   the task.

## Result

`test_parseltongue_core_consistency.py` passes clean — 7 hard passes,
one xfail left (the compression-target report, out of this task's
scope). Zero danglings, zero issues; the bench screen on core_clean
shows warnings only.

- All stale evidence re-grounded against current sources; ground truth
  moved with the code (grammar.pltg for the reader/printer, matcher
  facts in lang.pltg, dsl_loader.py and engine_stack.py registered).
- Landed TODO stubs graduated into grounded facts with pairings; the
  17 stub-sided diffs filled with real README documentation; README
  plan records became machine-checked :absent corpus claims.
- std library got behavioral coverage (std_behavior.pltg exercises
  every previously-unused definition with cross-route diffs).
- The alias story concluded in a language feature: entity imports
  ((import (quote mod.entity [local]))) bind one directive under any
  name with shared identity, replacing the defterm-alias idiom and the
  measure special-casing it required. verify_manual/reverify_evidence
  write back alias-preserving; dangling measures collapse alias
  shadows via one shared helper.
- Bench fixes surfaced along the way: corpus-aware screen cache keys,
  reload preserving the corpus, corpus verifier rooted at the project
  root, closure walks pruned, incremental screens recomputing
  danglings, screens invalidating on any corpus mutation.
- Follow-ups tracked as their own tasks: wire-inspect-validators,
  deepen-core-evidence, coverage-in-consistency-report,
  eliminate-confounded-diff-evidence, pgmd-roadmap-tracker.
