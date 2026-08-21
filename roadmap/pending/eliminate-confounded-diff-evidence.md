# Eliminate Confounded Diff Evidence

## Problem

`confounded_evidence` now detects when both sides of a `diff` reach the
same source quote, or when one same-document quote fully contains the
other. Running it over `core_clean.pltg` exposes 152 confounded diffs.
The largest concentrations are the top-level validation graph (30),
engine (22), quote verifier (18), demos (17), and loader (14).

These comparisons may still agree numerically, but shared evidence
means they are not independent corroboration. Common patterns include
two aggregates rebuilt from the same facts, documentation and
implementation branches that both inherit one documentation quote,
and coverage matrices that compare a list with a count derived from
that same list.

The whole-estate `test_no_confounded_evidence` records this debt as a
strict xfail. That makes the debt visible but does not resolve it.

## What we want

- Zero `confounded_evidence` warnings from `core_clean.pltg` and the
  top-level `parseltongue.pltg` self-validation entry.
- Remove the strict xfail from `test_no_confounded_evidence`; the test
  must pass as an ordinary required consistency invariant.
- Preserve meaningful independent layers. Typical valid pairings are
  documentation vs implementation, declaration vs runtime behavior,
  or two independently sourced documents.
- When a comparison is inherently based on one source, replace the
  `diff` with an honest derivation or coverage assertion instead of
  presenting it as cross-validation.

## Cleanup rules

- Do not evade detection by splitting one passage into overlapping or
  cosmetically different quotes.
- Do not duplicate a fact, rename an alias, or rebuild the same count
  on the opposite side and call it independent.
- Follow transitive provenance, not just the immediate `:replace` and
  `:with` directives.
- Keep a diff only when its sides can fail independently for a real
  change in one layer.
- Fix the highest-density families first: generic `*-coverage` diffs,
  `paired-vs-*` matrices, and the top-level self-comparisons.

## Acceptance criteria

1. `python -m parseltongue load_main parseltongue.pltg` reports no
   `confounded_evidence` warning.
2. `test_no_confounded_evidence` has no xfail marker and passes.
3. The full consistency suite retains zero issues and zero dangling
   definitions.
4. Each rewritten validation family documents which independent
   ground-truth layers its remaining diffs compare.

