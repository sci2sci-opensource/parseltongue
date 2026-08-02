# Consistency Coverage

## Problem

We don't know how much of the loaded documents is actually covered by quotes and converted to facts. A .pltg file might quote 30% of a source document and leave 70% unexamined. There's no metric for "how thoroughly did we inspect this document?"

## What we want

A coverage metric per document: what fraction of the document's content is covered by evidence quotes? This tells the user:
- Which documents are well-covered vs barely touched
- Where to add more facts/axioms to improve coverage
- Whether a "consistent" result is meaningful (consistent over 10% coverage is weaker than consistent over 90%)

## Approach

The QuoteVerifier already knows which ranges of each document are quoted (via `_quote_ranges`). Coverage = union of quoted ranges / total document length. Surface this as:
- Per-document coverage percentage
- Overall coverage across all documents
- Visual indicator in the viz (document nodes colored by coverage)

## Files likely involved

- `quote_verifier/index.py` — has the quote ranges, needs a coverage calculation method
- `evaluation.py` (or `screen.py` post-rename) — include coverage in the health report
- `bench_cli.py` — surface via a CLI command
- `renderer.py` / `detail.js` — show in viz

## Shipped

Coverage landed as typed measurements over verification state, not
language: a frozen Coverage base whose ClassVar type is decisive for
the subtype shape, providers registered per type on System (the
composition layer) — quote_range (merged verified-quote spans over
normalized document length) and corpus_claim (grounded :absent/:forall
claims per document) as the built-ins, richer kinds pluggable without
core changes. Surfaced via Bench.coverage(), pg screen --what coverage,
and the viz health view's per-document chart. First real run measured
the core spec itself at 11% average quote coverage.
