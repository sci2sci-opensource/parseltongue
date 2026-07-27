# Universal Obligations — every X must be accompanied by Y

## Problem

[Absence evidence](absence-evidence.md) makes "X appears nowhere" statable. The natural next quantifier is the co-occurrence invariant: "every X is accompanied by Y." These are the workhorse claims of real audits — every route handler carries an auth decorator, every migration has a reverse, every `unsafe` block has a justification comment, every public function has a docstring — and none of them is currently expressible. A reviewer can only check examples; the language should state the rule and hold the whole corpus to it.

## What we want

An evidence form asserting that every match of a pattern satisfies a companion condition within a scope:

```
(fact all-routes-authed true
  :evidence (:forall (re "@app\\.route")
             :satisfies (near 5 (re "@requires_auth"))
             :scope (in "src/api")
             :except ("tests/")))
```

Verification is a posting-set difference over the existing search operators:
`matches(X) − matches(X satisfying Y)` restricted to scope-minus-except must be empty.

Properties, shared with absence evidence by construction:

1. **Failures produce quotes.** When the obligation is violated, the counter-examples are postings — file, line, context — rendered exactly like search results. The fact flips to false and taints every derive downstream via the ordinary propagation machinery.

2. **Closure gate.** The verifier refuses to certify a `:forall` fact if the scope contains unclassified or guardrail-skipped files — same soundness rule as `:absent`. A universal claim is only assertable when the corpus it quantifies over is closed.

3. **Self re-verification.** The obligation goes stale exactly when the index changes within its scope; re-checking is a pair of index queries, cheap enough for every reindex pass. Provenance records `(pattern, satisfies, scope, merkle-root, violations=0)`.

Absence is the degenerate case: `:absent Q` ≡ `:forall Q :satisfies (never)`. Implementation should treat them as one evidence family with two surface forms, so the closure gate, staleness tracking, and screen category are built once.

## Approach

- **Evidence grammar**: extend the `:evidence` parser with the `:forall` / `:satisfies` form; `:scope` and `:except` shared with `:absent`.
- **Satisfies operators**: any search S-expression evaluable relative to a match — `near N`, `seq`, `in` (same document), plus plain sub-queries. Start with `near`/`seq`/same-document; these cover the co-occurrence use cases without inventing new operators.
- **Verification**: evaluate both posting sets through the search system, subtract, require empty; store the counter-example postings on failure for screen/viz display.
- **Screen**: violations surface as a distinct category (`obligation-violated`) with the counter-example lines; scope-closure failures surface with the same actionable message as absence (`.pgignore` it, allowlist it, or narrow the scope).
- **`diff` integration**: spec-side requirements ("all endpoints must be authenticated") cross-validate against implementation-side `:forall` facts, closing the compliance loop for mandates the same way `:absent` closes it for prohibitions.

## Files likely involved

- Same surface as [absence evidence](absence-evidence.md) — evidence parsing, quote-verifier entry point, search system query evaluation, store (scoped merkle roots + skipped-files report), screen categories, docs and a demo claim. The two should land as one family, `:absent` first or together.

## Non-goals

- No quantification beyond the indexed corpus; the closure gate is the boundary.
- No graded compliance ("95% of routes") — an obligation holds or it is violated with counter-examples. Percentages are a display concern for the screen, not a truth value.
