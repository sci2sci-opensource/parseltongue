# Absence Evidence — proving that something is NOT there

## Problem

Every parseltongue fact is grounded in a verbatim quote, so the language can only speak about *presence*. But the highest-value claims in the flagship use cases are negative: *no* MD5 anywhere in the auth module, *no* `eval` in the request path, *no* hardcoded secrets, *no* direct DB access from the client layer. Today those claims are unstatable — a fact like `no-weak-hash` can exist only as an unverifiable assertion, which is exactly the kind of claim the language exists to forbid. The security-audit story is half-complete: quote verification catches *fabricated presence* ("passwords are hashed with bcrypt" when there's no bcrypt), but nothing can *prove absence* ("MD5 is never used"), even though missing-the-real-vulnerability is the failure mode the README leads with.

Absence over an open world is unsound — but pg-bench already maintains the two things that make it sound within a bench:

1. a **closed, versioned corpus**: the full-text index with a Merkle root, and
2. the **classification discipline** from the size guardrail: every file in an indexed tree is either ignored (`.pgignore`), indexed, or explicitly allowlisted — never silently skipped.

That is precisely the closure property negation-as-failure needs. The pieces exist; they're not wired into the evidence system.

## What we want

A new evidence form asserting that a search query has zero matches within a scope of the indexed corpus:

```
(fact no-weak-hash true
  :evidence (:absent (re "md5|sha1")
             :scope (in "src/auth")
             :except ("tests/")))
```

Verification runs the query against the index and records `(query, scope, merkle-root, count=0)`. The provenance is *the whole scoped corpus at that root*, not a quote.

Three properties should hold by construction:

1. **Soundness gate**: the verifier refuses to certify an `:absent` fact if the scope contains unclassified or guardrail-skipped files. The absence claim is only assertable when corpus closure holds — absolute claims become invariants of the mechanism enforcing them, not survey results.

2. **Self re-verification**: an absence fact goes stale exactly when the index changes within its scope, and re-checking is one index query — cheap enough to run on every reindex pass. Presence facts need quote re-verification; absence facts keep themselves honest. A violated absence fact flips to false and taints every derive downstream, via the same propagation machinery as a failed quote.

3. **Closing the compliance loop**: `diff` directives can finally cross-validate prohibitions. Spec side extracts "MD5 is prohibited"; implementation side proves `:absent (re "md5")`; the diff checks them against each other mechanically. Today that loop dead-ends at the negative side.

## Approach

- **Evidence grammar**: extend `:evidence` parsing to accept an `:absent` form carrying a search S-expression, an optional `:scope` restriction (document/glob/path-prefix, same semantics as the search `(in ...)` operator), and optional `:except` exclusions.
- **Verification**: evaluate the query through the search system at fact-load / screen time; require the posting set restricted to scope-minus-except to be empty. Record the Merkle root of the scoped subtree alongside the result.
- **Closure check**: before certifying, intersect the scope with the guardrail's skipped-files report and the set of files excluded by extension config. Any overlap → verification fails with an actionable message (add to `.pgignore`, allowlist, or narrow the scope) — mirroring the guardrail's "every file must be classified" philosophy.
- **Staleness**: on reindex, re-run absence queries whose scope intersects the changed/deleted/added paths. Zero matches → re-pin to the new root; matches → flip the fact, surface in screen as a distinct category (`absence-violated`, with the offending postings as counter-evidence — the failure produces *quotes*, pleasingly).
- **Screen / viz**: absence facts render with their scope + root provenance; a violation shows the counter-example lines exactly like search results.

## Non-goals

- No probabilistic or graded belief — absence is binary and scoped, like everything else in the language.
- No filesystem claims beyond the indexed corpus: `:absent` quantifies over the index, and the closure gate is what makes that an honest boundary rather than a loophole.

## Files likely involved

- `parseltongue/core/loader/` + evidence parsing — the `:absent` grammar.
- `parseltongue/core/quote_verifier/` — verification entry point alongside quote verification.
- `parseltongue/core/inspect/search.py` / `systems/search_system_2.py` — scoped query evaluation + counter-example postings.
- `parseltongue/core/inspect/store.py` — Merkle root of a scoped subtree; skipped-files report for the closure gate.
- `parseltongue/core/inspect/screen.py` / `evaluation.py` — `absence-violated` category, staleness re-checks.
- Docs: core README (evidence section), kung-fu learning path, a demo (`code_check` gains an absence claim).

## Origin

Proposed from language-design review after the daemon/refresh hardening work: the search index, Merkle roots, and guardrail classification already form a closed world per bench — absence evidence is the latent capability those pieces jointly enable.

## Shipped

Landed as `:absent` on the existing evidence form — no new grammar head;
`Evidence` gained a typed interior (source/claims) and a `type`
discriminator, with `document`/`quotes` as interface-preserving views.
Verification dispatches through a per-type registry injected at the
System/Engine constructor. Core grounds claims against the
registered-document corpus (closed by construction, content-hash
provenance, re-grounding on register_document); the bench overrides with
the file-corpus verifier — closure gate, scoped Merkle root,
reindex-driven re-verification. Along the way the search engine was
promoted to core (`core/search_engine`, QueryEngine) and `load-documents`
added for bulk corpus loading with the indexer's selection mechanics.
First consumer: `validation/architecture.pltg` — core-independent-of-bench
as a composite of per-import-vector absence facts.
