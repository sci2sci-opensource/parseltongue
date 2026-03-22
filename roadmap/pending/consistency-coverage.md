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
