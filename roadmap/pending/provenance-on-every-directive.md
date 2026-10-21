# Provenance on Every Directive — Optional Evidence and Explanation for Derive and Diff

## Problem

`fact`, `axiom` and `defterm` take `:evidence` (with its `:quotes` and
`:explanation`) or `:origin`: each says where it comes from and why
(`DSLLoader.resolve_origin`). `derive` and `diff` take neither. A theorem's
only provenance is its derivation, and a diff carries nothing beyond its two
sides.

But a derive is often a claim someone made in a document, not only a
consequence someone computed: "a dataset estate is compliant when the
violation count is zero", "the dose agrees with the protocol". The reason it
is checked, and the passage that asks for it, are as much its provenance as
the facts it uses. Today that text lives on a neighbouring fact or in a
comment, where the screen, the evidence views and the quote coverage do not
see it. Likewise a diff states that two things should agree, and the
requirement that says so has nowhere to go.

## What we want

- `derive` and `diff` accept the same optional provenance keywords as the
  other top-level directives: `:evidence` (quotes, explanation) or
  `:origin`. Omitted, nothing changes.
- The derivation stays what decides a theorem's truth. Evidence on a derive
  is a second, documentary account beside it: verified like any evidence
  (quotes grounded in their document), shown with it, counted in coverage,
  never a substitute for the proof.
- One shape for provenance on every top-level directive, so a reader, a
  validator or a view asks the same question of any node: where does it come
  from, and why.
- The screen reports a derive's or a diff's evidence the way it reports a
  fact's (unverified quotes, missing documents).

## Approach (sketch)

- `DSLLoader.execute_directive`: read `resolve_origin(expr)` for `DERIVE` and
  `DIFF`, and hand it to `engine.derive` / `engine.register_diff` as an
  optional `origin`.
- The theorem and diff atoms carry it beside what they carry now (a theorem
  keeps its derivation as its truth; the evidence is reported, not used to
  decide).
- Verification, coverage and the screen treat it like any directive's
  evidence; the viz and notebook payloads carry it as they carry a fact's.
- Grammar documentation and the directive tables list the keywords on every
  top-level directive.

## Files likely involved

`parseltongue/core/dsl_loader.py`, `parseltongue/core/engine.py` and the
engine stack (`derive`, `register_diff`), the atoms (`Theorem`, the diff
record), `parseltongue/core/ast.py` (dependency extraction from the new
keywords), the screen and coverage under `parseltongue/core/inspect/`, the
grammar docs.
