# Core Consistency Test — Stabilisation Phase

## Problem

`test_parseltongue_core_consistency.py` currently fails. The core .pltg files need significant updates to pass the consistency check. This is known technical debt.

## Status

Postponed to the stabilisation phase. The core .pltg coverage was built incrementally and has accumulated inconsistencies (8 derives without diffs in core, known dangling counts, etc.). Fixing this requires a focused pass through all core .pltg files to align facts, evidence, and derives with the current codebase state.

## What's needed

- Audit all core .pltg files for stale quotes, missing diffs, dangling definitions
- Update evidence quotes to match current source code
- Add missing diffs for derives that lack them
- Verify all fact values match reality
- Get `python -m pytest parseltongue/core/tests/test_parseltongue_core_consistency.py -q` to pass clean
