# Core Consistency Test — Stabilisation Phase

**Branch**: feature/core-consistency-stabilisation

## Problem

`test_parseltongue_core_consistency.py` currently fails. The core .pltg files need significant updates to pass the consistency check. This is known technical debt.

## Status

Claimed. The core .pltg coverage was built incrementally and has accumulated inconsistencies (stale evidence quotes, dangling counts, unfilled stub sides of diffs, etc.). Fixing this requires a focused pass through all core .pltg files to align facts, evidence, and derives with the current codebase state.

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
