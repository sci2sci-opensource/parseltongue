---
name: parseltongue-bench
description: Use pg-bench CLI daemon for instant .pltg inspection — search, lens, diagnose, dissect, compose. Activates when working with .pltg files, debugging consistency, tracing provenance, or exploring parseltongue codebase. Always prefer pg-bench over grep/read for this codebase.
user-invocable: true
---

# pg-bench

Persistent daemon that holds a loaded .pltg Bench in memory. Start once, query instantly.

## Start

```bash
pg-bench serve parseltongue/core/validation/core.pltg & pg-bench wait
pg-bench index parseltongue/core   # index .py .pltg .md .txt — do this!
```

`wait` blocks until bench is ready (~200ms with Merkle cache). No sleep needed — socket opens immediately, `wait` polls until bench status leaves `initialized`.

Always index with all default extensions. The .md and .pltg files matter — pltg nodes quote from them.

## Search: S-expression query language

Queries starting with `(` are parsed as pltg S-expressions and evaluated by a real System whose operators work on posting sets.

```bash
# Literal phrase
pg-bench search "raise ValueError"

# OR — union
pg-bench search '(or "raise ValueError" "raise SyntaxError")'

# AND — intersection (same line must match both)
pg-bench search '(and "import" "quote")'

# NOT — difference
pg-bench search '(not (in "engine.py" "raise") "KeyError")'

# IN — document filter (exact, suffix, or glob)
pg-bench search '(in "engine.py" "raise")'       # only engine.py, not test_engine.py
pg-bench search '(in "tests/*" "raise")'          # glob

# NEAR — proximity within N lines
pg-bench search '(near "raise" "ValueError" 2)'

# RE — regex
pg-bench search '(in "engine.py" (re "raise (ValueError|NameError)"))'

# SEQ — a before b in same document
pg-bench search '(seq "def derive" "raise")'

# LINES — range filter
pg-bench search '(lines 400 500 (in "engine.py" (re ".")))'

# COUNT
pg-bench search '(count (in "engine.py" "raise"))'

# Compose freely
pg-bench search '(not (in "engine.py" (near "raise" "ValueError" 3)) "KeyError")'
```

Results include pltg provenance: `[engine.derivation-impl-count] def derive(` — the pltg node that quotes that line.

## Lens: structural navigation

```bash
pg-bench find "error"              # regex over all pltg names
pg-bench fuzzy "eval"              # ranked substring search
pg-bench view engine.eval-bind     # single node — full quotes, file:line, confidence
pg-bench view                      # entire structure
pg-bench focus "engine."           # narrow to namespace
pg-bench consumer engine.derive    # node with its inputs
pg-bench inputs engine.derive      # just the inputs
pg-bench subgraph engine.derive    # upstream dependencies
pg-bench subgraph engine.derive -d downstream
pg-bench subgraph engine.derive -d both
pg-bench kinds                     # node kinds with counts
pg-bench roots                     # root nodes
```

## Hologram: multi-lens views

```bash
# Dissect a diff — side-by-side Hologram of both sides
pg-bench dissect atoms.theorem-derivation-sources

# Compose N names — parallel lenses
pg-bench compose engine.eval-bind engine.derive
```

## Diagnosis

```bash
pg-bench diagnose                          # summary
pg-bench diagnose --what issues            # only failures
pg-bench diagnose --what ok                # only passing
pg-bench diagnose --focus "engine."        # focus on namespace
```

## Operations

```bash
pg-bench ping      # "pong" when ready, "loading" during prepare
pg-bench wait      # blocks until ready — use after backgrounded serve
pg-bench status    # path, status, integrity
pg-bench reload    # invalidate + re-prepare
```

Typical cold start is ~200ms (Merkle cache). Chain as single command:

```bash
pg-bench serve core.pltg & pg-bench wait && pg-bench find "engine"
```

## Bench first, grep second

This codebase is heavily covered by .pltg. The fastest path:
1. `pg-bench find`/`fuzzy` — instant structural nodes with file:line
2. `pg-bench search` — full-text with provenance tracing
3. grep/glob — only for things outside pltg coverage

Bench is cached via Merkle trees. After first load, queries are ~2ms.

## Languages TBD

The S-expression search language uses a real pltg System with posting-set operators. The same approach can be extended to:
- **Diagnosis queries** — filter/combine diagnostic results with S-expressions
- **Lens queries** — structural navigation expressed as S-expressions
- **Hologram queries** — bias selection and composition as expressions

These are natural extensions — the System infrastructure is already there.
