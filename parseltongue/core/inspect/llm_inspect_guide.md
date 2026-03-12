# Inspect & Lens — loading and analyzing `.pltg` code

Guide for an LLM agent that needs to load parseltongue files, build provenance structures, and render views.

## Quick start — use Bench

**Bench is the recommended entry point.** Prepare a sample, then observe with `lens()` (structure), `diagnose()` (health), or `search()` (full-text with provenance). Backed by Merkle tree caching with eventual consistency.

```python
from parseltongue.core.inspect.bench import Bench

bench = Bench()  # caches to .parseltongue-bench/

bench.prepare("parseltongue/core/validation/core_clean.pltg")

lens = bench.lens()          # structural observation (Lens)
dx   = bench.diagnose()      # consistency observation (Diagnosis)
r    = bench.search("def")   # full-text search with provenance
```

Bench caches per resolved file path. Edit a file and call `bench.prepare()` again: Merkle tree diff detects which files changed, hot-patches the system, and re-probes only affected nodes. Diagnosis is also incremental — only diffs affected by changed names are re-evaluated. A background loader runs to reach full integrity.

### When to use what

| Need | Use |
|------|-----|
| Load + probe + cache (default) | `bench.prepare(path)` then `bench.lens()` / `bench.diagnose()` / `bench.search()` |
| Full-text search with provenance | `bench.search(query)` |
| Probe a single term by name | `inspect_loaded(term, loader)` → `Lens` |
| Probe without file:line | `probe(term, engine)` → structure, then `inspect(structure)` |
| Full-engine probe | `probe_all(result)` → structure with all roots |

## Search API

`bench.search()` composes full-text document search with pltg quote provenance tracing. Every verified quote registers its position — search finds text, then traces which pltg nodes quote that region.

```python
r = bench.search("def retract")

# Result structure
r["total_lines"]    # total matching lines across all documents
r["total_callers"]  # total unique pltg nodes overlapping
r["offset"]         # current page offset
r["lines"]          # list of line results

# Each line
for line in r["lines"]:
    print(f'{line["document"]}:{line["line"]}  {line["context"]}')
    for c in line["callers"]:
        print(f'  <- {c["name"]}  overlap={c["overlap"]}')
    # line["total_callers"] = total callers (may exceed max_callers)
```

### Ranking strategies

```python
bench.search("def", rank="callers")    # most pltg nodes quoting the line first (default)
bench.search("def", rank="coverage")   # best quote overlap first
bench.search("def", rank="document")   # grouped by document, most hits per doc first
```

| Ranking | Sorts by |
|---------|----------|
| `callers` | Lines with most pltg callers first, then untraced |
| `coverage` | Best overlap ratio first, then by caller count |
| `document` | By document (most total hits first), traced lines first within |

### Pagination

```python
bench.search("def", max_lines=10, offset=0)   # page 1
bench.search("def", max_lines=10, offset=10)  # page 2
bench.search("def", max_callers=3)             # cap callers per line
```

### Direct access to Search engine

```python
from parseltongue.core.inspect.search import Search, Ranking
from parseltongue.core.inspect.store import SearchStore

search = Search(SearchStore(index=engine._verifier.index))
r = search.query("consistency", rank=Ranking.DOCUMENT, max_lines=20, offset=0)
```

### CLI commands (pg-bench)

```bash
# Index a directory into the search engine
pg-bench index parseltongue/core

# Reindex known files (only reports changed files)
pg-bench reindex

# Purge all caches (memory + disk) and reload
pg-bench purge

# Start server with background reindex every 60 seconds
pg-bench serve path/to/file.pltg --refresh-index 60
```

## Lens API

All `view_*` methods take an optional perspective class (defaults to first registered — `MDebuggerPerspective` from Bench).

```python
lens = bench.lens()

# Full structure
print(lens.view())

# Search
lens.find("count")              # regex search over names
lens.fuzzy("special-form")      # substring match, ranked

# Focus on one term — returns new Lens narrowed to substructure
focused = lens.focus("readme.special-forms-count")
print(focused.view())

# View individual nodes
print(lens.view_node("std.epistemics.hallucinated"))
print(lens.view_consumer("engine.hallucinated-count"))
```

| Method | Returns |
|--------|---------|
| `lens.view()` | Full structure as pltg code in topological order |
| `lens.view_layer(depth)` | One layer as a table |
| `lens.view_consumer(name)` | Single consumer: code + metadata + inputs |
| `lens.view_node(name)` | Node without inputs — pltg form + metadata |
| `lens.view_inputs(name, *input_types)` | Inputs table, optionally filtered by `InputType` |
| `lens.view_subgraph(name, direction)` | Dependency tree: `"upstream"`, `"downstream"`, `"both"` |
| `lens.view_kinds()` | Table of node kinds with counts |
| `lens.view_roots()` | Root nodes (layer 0) |
| `lens.focus(name)` | New Lens narrowed to substructure around `name` |
| `lens.find(pattern)` | Regex search over names |
| `lens.fuzzy(query)` | Substring match, ranked by relevance |

### Input types

Each `Consumer` classifies its inputs:

| InputType | Meaning |
|-----------|---------|
| `USE` | References a root (axiom/forward term) via `:using` |
| `DECLARE` | Inline fact at depth 0 |
| `PULL` | Result from a shallower layer |

Filter with:
```python
from parseltongue.core.inspect.probe_core_to_consequence import InputType
lens.view_inputs("module.theorem", InputType.PULL)
```

## Diagnosis API

`bench.diagnose()` returns a `Diagnosis` — the health side of observation. Wraps consistency into a searchable, focusable object.

```python
dx = bench.diagnose()

# Overview
print(dx.summary())           # counts by category and type
print(dx.consistent)          # bool — no issues?
print(dx.stats())             # dict: by_category, by_type, by_kind, by_namespace, by_file

# Filter
dx.issues()                    # all issues
dx.issues(kind="diff")         # only diff issues
dx.issues(type="divergence")   # by issue type
dx.warnings()                  # all warnings
dx.warnings(namespace="engine.")  # engine warnings only
dx.danglings()                 # unused definitions
dx.danglings(kind="derive")   # unused derives
dx.loader()                    # loader errors, skips, warnings

# Search
dx.find("count")               # regex over all names in diagnosis
dx.fuzzy("special")            # substring match, ranked

# Focus — narrow to namespace, returns new Diagnosis
rdx = dx.focus("readme.")
print(rdx.summary())
print(rdx.issues())
```

Each item is a `DiagnosisItem` with: `name`, `category` (issue/warning/dangling/loader), `type`, `kind` (directive kind), `loc` (file:line), `detail`.

## Perspectives

Perspectives are **instances** registered on lens creation. Bench registers `MDebuggerPerspective` by default.

| Perspective | What it adds |
|-------------|-------------|
| `MDebuggerPerspective(loader)` | `file:line` on every node — **default from Bench** |
| `MarkdownPerspective()` | Plain markdown, no locations |
| `AsciiPerspective()` | Terminal-friendly plain text |

`MDebuggerPerspective` is critical for LLM workflows — `.pltg` files can be thousands of lines, and without line references you'd have to search. Detail views (`view_node`, `view_consumer`) show full quotes with document line number and confidence score.

## Diffs — not traversed by probe

`probe` walks terms, facts, axioms, theorems — not diffs. To debug a failing diff, use `dx.issues(kind="diff")` to find failures, then lens each side:

```python
bench.prepare("parseltongue/core/validation/core_clean.pltg")
dx = bench.diagnose()

# Find failing diffs
for item in dx.issues(kind="diff"):
    print(f"{item.name} @ {item.loc}")

# Lens both sides of a diff
engine = bench.engine
diff = engine.diffs["thm-readme-special-forms"]

from parseltongue.core.inspect import inspect_loaded
result = bench.result()
lens_expected = inspect_loaded(diff["replace"], result.loader)
lens_actual   = inspect_loaded(diff["with"], result.loader)

print(lens_expected.view())
print(lens_actual.view())
```

## Workflow — finding and fixing a divergence

### 1. Search for the code

```python
bench = Bench()
bench.prepare("parseltongue/core/validation/core_clean.pltg")

# Find code and which pltg nodes reference it
r = bench.search("def register_document")
# → engine.py:298 ← [engine.engine-has-register-document(1.0)]
```

### 2. Diagnose

```python
dx = bench.diagnose()

# Failing diffs
for item in dx.issues(kind="diff"):
    print(f"{item.name} @ {item.loc}")

# Focus on a namespace
edx = dx.focus("engine.")
print(edx.summary())
```

### 3. Lens both sides

```python
engine = bench.engine
diff = engine.diffs["thm-readme-special-forms"]

from parseltongue.core.inspect import inspect_loaded
result = bench.result()
lens_expected = inspect_loaded(diff["replace"], result.loader)
lens_actual   = inspect_loaded(diff["with"], result.loader)

print(lens_expected.view())
print(lens_actual.view())
```

### 4. Detail view for exact locations

```python
lens = bench.lens()
print(lens.view_node("lang.special-forms-tuple-size"))
```

Shows the quote, document line, confidence score. Now you know exactly where to edit.

### 5. Fix and verify

```python
# Quick check
r = engine._resolve_value(diff["replace"])
w = engine._resolve_value(diff["with"])
print(f"{r} == {w}: {r == w}")

# Or reload via bench — detects changes, re-probes incrementally
bench.prepare("parseltongue/core/validation/core_clean.pltg")
dx = bench.diagnose()
print(dx.summary())
```

## Bench internals

### Status and integrity

Bench tracks two states per sample:

| State | Values | Meaning |
|-------|--------|---------|
| `bench.status[path]` | `initialized` / `loading` / `live` | Lifecycle: no load → background loader running → fully operational |
| `bench.integrity[path]` | `corrupted` / `unknown` / `verified` | Change detected → hot-patched but unverified → confirmed by full reload |

Cold load: `status=live, integrity=verified` immediately.
Disk cache hit: `status=loading, integrity=verified` — deserialized system works, background loader produces live system.
Incremental (file changed): `status=loading, integrity=unknown` — hot-patched system available, background loader verifies via Merkle tree comparison.

### Caching

Bench uses file-level Merkle trees — each source file (`.pltg` + loaded documents) is a leaf. Full system state (including verifier index) is serialized to disk.

On `bench.prepare(path)`:
1. Hash all source files, build Merkle tree
2. Compare root hash with cached — if match, return cached (~2ms memory, ~80ms disk)
3. On mismatch: find changed files, hot-patch system (retract + re-execute + re-probe affected), start background reload (~200ms)
4. No cache: cold load (~4s)

On `bench.diagnose()`:
1. Memory cache hit → return immediately
2. Disk cache with matching Merkle root → return from disk
3. Incremental: stale diagnosis + affected names from prepare → re-evaluate only affected diffs → patch old diagnosis
4. Cold: full consistency check

```python
bench.invalidate("path.pltg")  # clear cache for one file
bench.invalidate()              # clear all caches
```

### Verifier index serialization

The QuoteVerifier's `DocumentIndex` is serialized with the system — normalized text and position maps are stored, skipping the expensive `normalize_with_mapping` on restore. Content hashes per document detect changes: unchanged documents restore instantly, changed ones re-index only that document. Quote provenance ranges (caller → document position) are rebuilt on load, not serialized.

## When to search vs lens

| Goal | Use |
|------|-----|
| Find text in source code | `bench.search("text")` — returns document locations + pltg callers |
| Navigate pltg structure | `lens.find("name")` / `lens.fuzzy("name")` — searches node names |
| View a specific node | `lens.view_node("name")` — pltg form + metadata + location |
| Trace code → pltg | `bench.search("code")` — callers show which pltg nodes quote that code |
| Trace pltg → code | `lens.view_node("name")` — shows quoted source with document line |
