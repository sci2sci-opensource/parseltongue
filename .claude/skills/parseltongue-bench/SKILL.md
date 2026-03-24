---
name: parseltongue-bench
description: Use pg-bench CLI daemon for instant .pltg inspection — search, lens, diagnose, dissect, compose. Activates when working with .pltg files, debugging consistency, tracing provenance, or exploring parseltongue codebase. Always prefer pg-bench over grep/read for this codebase.
user-invocable: true
---

# pg-bench

Persistent daemon that holds a loaded .pltg Bench in memory. Start once, query instantly.

eval and interpret are the primary interface. eval is pure (clean copy each time), interpret accumulates state (clean resets it). Both accept S-expressions with the full std library, scopes (lens, screen, ops, search, hologram), and fmt for formatted output.

## Start

```bash
pg-bench serve parseltongue/core/validation/core.pltg & pg-bench wait
pg-bench index parseltongue/core   # index .py .pltg .md .txt — do this!
```

`wait` blocks until bench is ready (~200ms with Merkle cache). No sleep needed — socket opens immediately, `wait` polls until bench status leaves `initialized`.

Start variants:
- `pg-bench serve file.pltg` — foreground (blocking)
- `pg-bench start file.pltg` — daemonized (returns immediately)
- `pg-bench up file.pltg` — foreground; `pg-bench up -d` to detach

Lifecycle: the server loads a frozen cache immediately (~20ms) so queries work right away, then computes a live evaluation in a background thread. Use `pg-bench status` to check whether the bench is frozen or live.

Always index with all default extensions. The .md and .pltg files matter — pltg nodes quote from them.

## Eval: pure S-expression evaluation

```bash
pg-bench eval '(+ 1 2)'                          # bare expression
pg-bench eval '(scope lens (find "engine"))'      # lens scope
pg-bench eval '(scope screen (issues))'           # screen scope
pg-bench eval '(fmt "viz" (scope lens (kind "fact")))' > out.html  # viz
pg-bench eval -f script.pltg                      # from file
echo '(+ 1 2)' | pg-bench eval                   # from stdin
pg-bench '(+ 1 2)'                                # shorthand (default cmd)
```

Pure — uses a clean copy of the loaded system. Never polluted by interpret. See `pg-bench eval --help` for the full operator reference.

## Interpret: stateful directive execution

```bash
pg-bench interpret '(defterm my-val 42 :origin "test")'
pg-bench interpret '(fact check true :evidence ("f.py" :quotes ("x")))'
pg-bench interpret -f setup.pltg
pg-bench clean                                    # reset interpret scope
```

Like eval, but also accepts directives (defterm, fact, axiom, derive). State accumulates across calls. Does not affect the main loaded system or the eval scope.

## Scopes

Scopes are registered subsystem query languages accessible via `(scope name expr)`.

### Lens scope — structural navigation over the pltg graph

```bash
pg-bench eval '(scope lens (kind "fact"))'        # all fact nodes
pg-bench eval '(scope lens (inputs "engine.derive"))'  # upstream deps
pg-bench eval '(scope lens (downstream "engine.derive"))'  # dependents
pg-bench eval '(scope lens (roots))'              # root nodes
pg-bench eval '(scope lens (layer 2))'            # nodes at depth 2
pg-bench eval '(scope lens (focus "engine."))'    # namespace filter
pg-bench eval '(scope lens (find "engine.eval"))'  # regex search
pg-bench eval '(scope lens (fuzzy "derive"))'      # substring search
pg-bench eval '(scope lens (terms "axiom"))'       # list of names
pg-bench eval '(scope lens (quotes "name"))'       # quote strings
pg-bench eval '(scope lens (atom "name"))'         # atom as tagged list
```

### Screen scope — consistency results (alias: diagnose, evaluation)

```bash
pg-bench eval '(scope screen (issues))'           # all failing diffs
pg-bench eval '(scope screen (warnings))'         # all warnings
pg-bench eval '(scope screen (danglings))'        # dangling definitions
pg-bench eval '(scope screen (loader))'           # loader issues
pg-bench eval '(scope screen (focus "engine."))'  # namespace filter
pg-bench eval '(scope screen (find "engine"))'    # regex search
pg-bench eval '(scope screen (consistent))'       # true if no issues
```

### Ops scope — fast set operations over tagged form lists

```bash
pg-bench eval '(scope ops (and-forms L1 L2))'     # intersection by key
pg-bench eval '(scope ops (or-forms L1 L2))'      # union
pg-bench eval '(scope ops (not-forms L1 L2))'     # difference
pg-bench eval '(scope ops (count-forms L))'        # count
pg-bench eval '(scope ops (str format "{}" (V data)))'  # format
pg-bench eval '(scope ops (list get (V data) N))'  # extract Nth field
```

### Hologram scope — after dissect/compose/stain

```bash
pg-bench eval '(scope hologram (left))'           # first lens
pg-bench eval '(scope hologram (right))'          # last lens
pg-bench eval '(scope hologram (divergent))'      # nodes that differ
pg-bench eval '(scope hologram (common))'         # nodes in all lenses
pg-bench eval '(scope hologram (only 0))'         # exclusive to lens 0
pg-bench eval '(scope hologram (dissect "diff-name"))'  # inline dissect
pg-bench eval '(scope hologram (compose n1 n2))'  # inline compose
pg-bench eval '(scope hologram (dissect (stain "name")))'  # live probe
```

### fmt — format bench forms for display

```bash
pg-bench eval '(fmt "md" (scope lens (kind "fact")))'     # markdown
pg-bench eval '(fmt "viz" (scope lens (focus "engine.")))' # HTML viz
pg-bench eval '(fmt "viz" (scope hologram (divergent)))'   # hologram viz
```

Perspectives: `"md"` (markdown), `"ascii"` (terminal), `"viz"` (interactive HTML).

## Viz: interactive HTML visualization

`(fmt "viz" expr)` renders any scope result as a self-contained HTML file with three view modes, search, kind filters, and an evidence panel. Pipe output to a file and open in browser.

```bash
# Lens views — structure graph
pg-bench eval '(fmt "viz" (scope lens (kind "fact")))' > temp/facts.html
pg-bench eval '(fmt "viz" (scope lens (focus "engine.")))' > temp/engine.html
pg-bench eval '(fmt "viz" (scope lens (kind "all")))' > temp/full.html

# Screen views — consistency issues
pg-bench eval '(fmt "viz" (scope screen (issues)))' > temp/issues.html
pg-bench eval '(fmt "viz" (scope screen (warnings)))' > temp/warnings.html

# Hologram views — side-by-side comparisons
pg-bench eval '(fmt "viz" (scope hologram (divergent)))' > temp/divergent.html
pg-bench eval '(fmt "viz" (scope hologram (common)))' > temp/common.html

# Composed pipelines — filter then visualize
pg-bench eval '(fmt "viz" (scope ops (and-forms (scope lens (kind "fact")) (scope lens (focus "engine.")))))' > temp/eng_facts.html
```

The HTML includes:
- **Cards view**: one card per node with kind dot, name, value, inputs
- **Layers view**: depth-based stacked layout showing the full dependency structure
- **Graph view**: D3 force-directed graph with zoom/pan, clickable nodes
- **Search bar**: live filter across all nodes
- **Kind filter**: toggle node kinds on/off (fact, axiom, theorem, term, diff)
- **Detail panel**: click any node to see full quotes, file:line, confidence scores, derivation tree

Works with all tagged form types: `ln` (lens), `dx` (screen), `sr` (search), `hn` (hologram). Cached on disk via Store for instant re-renders.

Always pipe to `temp/` — never to stdout for reading. Open the file in a browser.

## Search: S-expression query language

```bash
# Literal phrase
pg-bench search "raise ValueError"

# Set operators
pg-bench search '(and "import" "quote")'
pg-bench search '(or "raise ValueError" "raise SyntaxError")'
pg-bench search '(not (in "engine.py" "raise") "KeyError")'

# Document filter (exact, suffix, glob, or auto-glob bare name)
pg-bench search '(in "engine.py" "raise")'
pg-bench search '(in "tests/*" "raise")'
pg-bench search '(in "engine" "raise")'           # auto-glob *engine*
pg-bench search '(not-in "engine.py" "raise")'    # inverse

# Proximity, ordering, regex, line range
pg-bench search '(near "raise" "ValueError" 2)'
pg-bench search '(seq "def derive" "raise")'
pg-bench search '(re "raise (ValueError|NameError)")'
pg-bench search '(lines 400 500 (in "engine.py" (re ".")))'

# Context expansion
pg-bench search '(context 3 "raise")'             # N lines before + after
pg-bench search '(before 3 "raise")'              # before only
pg-bench search '(after 3 "raise")'               # after only

# Ranking and strategy
pg-bench search '(rank "callers" query)'          # rank by caller count
pg-bench search '(strategy "stemmed" "evaluate")'  # explicit strategy

# Count, limit, scope delegation
pg-bench search '(count (in "engine.py" "raise"))'
pg-bench search '(limit 5 query)'
pg-bench search '(scope lens (find "engine"))'
pg-bench search '(scope screen (issues))'

# Compose freely
pg-bench search '(not (in "engine.py" (near "raise" "ValueError" 3)) "KeyError")'
```

Results include pltg provenance: `[engine.derivation-impl-count] def derive(` — the pltg node that quotes that line.

## Lens: structural navigation (CLI shortcuts)

```bash
pg-bench find "error"              # regex over all pltg names (kind + file:line)
pg-bench fuzzy "eval"              # ranked substring search
pg-bench find "error" --scope screen  # only screen items
pg-bench view engine.eval-bind     # single node — full quotes, file:line, confidence
pg-bench view                      # entire structure
pg-bench focus "engine."           # narrow to namespace
pg-bench consumer engine.derive    # node with its inputs
pg-bench inputs engine.derive      # just the inputs
pg-bench subgraph engine.derive    # upstream dependencies
pg-bench subgraph engine.derive -d downstream
pg-bench subgraph engine.derive -d both
pg-bench kinds                     # node kinds with counts (diffs not yet in lens)
pg-bench roots                     # root nodes
```

## Hologram: multi-lens views (requires live)

```bash
# Dissect a diff — side-by-side Hologram of both sides
pg-bench dissect atoms.theorem-derivation-sources
pg-bench dissect atoms.theorem-derivation-sources --bias divergence

# Compose N names — parallel lenses
pg-bench compose engine.eval-bind engine.derive
pg-bench compose engine.eval-bind engine.derive --bias left

# Stain — trace evaluation at execution time (resolves dynamic terms)
pg-bench stain all-contract-facts-ok all-product-facts-ok
```

Biases control how lens outputs are combined: neutral (side by side), left (left primary), right (right primary), divergence (only differences). The hologram scope in the search system has analogous structural operators (divergent, common, only N) at the posting-set level.

## Diagnosis

```bash
pg-bench screen                            # summary
pg-bench screen --what issues              # only failures
pg-bench screen --what warnings            # only warnings
pg-bench screen --what danglings           # dangling definitions
pg-bench screen --what ok                  # only passing
pg-bench screen --what stats              # statistics
pg-bench screen --focus "engine."          # focus on namespace
pg-bench diagnose --what issues            # alias for screen
```

## History: time travel over indexed states

Each `pg-bench index` commits an immutable delta layer. Restore is non-destructive (appends reverse delta).

```bash
pg-bench history layers            # all layers with metadata
pg-bench history files             # files at current state
pg-bench history files -l 2        # files at layer 2
pg-bench history file NAME         # file content at current
pg-bench history file NAME -l 2    # file content at layer 2
pg-bench history diff              # diff layer 0 → latest
pg-bench history diff --from 1 --to 3  # diff between layers
pg-bench history diff-file NAME    # unified diff of one file
pg-bench history restore 2         # restore to layer 2
pg-bench history restore-file NAME 2  # restore one file
pg-bench history compact --yes     # squash all layers into one (destructive)
```

## Operations

```bash
pg-bench ping      # "pong" when ready, "loading" during prepare
pg-bench wait      # blocks until ready — use after backgrounded serve
pg-bench status    # path, status (frozen/live), integrity, loader errors
pg-bench reload    # invalidate memory cache + re-prepare (disk cache preserved)
pg-bench purge     # nuclear — wipe memory + disk caches, reload from scratch
pg-bench clean     # reset interpret scope (eval and live stay warm)
```

Typical cold start is ~200ms (Merkle cache). Chain as single command:

```bash
pg-bench serve core.pltg & pg-bench wait && pg-bench find "engine"
```

## Advanced usage patterns

### project — resolve in parent before crossing scope boundary

```bash
pg-bench eval '(scope lens (focus (project engine-prefix)))'
# Evaluates engine-prefix in the bench engine, passes result to lens scope
```

### delegate — defer resolution past current scope

```bash
pg-bench eval '(delegate (file-hits ?file))'
# Each scope posts a proposal; innermost success provides the result
```

### Map-reduce pipeline example

Pipeline: diagnostics → lens evidence → search intersection → per-file report.
Run via `pg-bench interpret -f pipeline.pltg`.

```scheme
; ── 1. Issues from diagnostics ──
(defterm issues (scope evaluation (issues)) :origin "all issues")

; ── 2. Enrich with lens evidence (intersect issues with full graph) ──
(defterm ln-issues
  (scope ops (and-forms (scope lens (kind "all")) (project issues)))
  :origin "ln forms for issue nodes"
  :using (issues))

; ── 3. Extract fields via vectorized ops ──
(defterm evidence      (scope ops (list get (V (project ln-issues)) 6)) :origin "ln-ev" :using (ln-issues))
(defterm issue-names   (scope ops (list get (V (project ln-issues)) 1)) :origin "names" :using (ln-issues))
(defterm issue-ev-docs (scope ops (list get (V (project evidence)) 1))  :origin "docs"  :using (evidence))

; ── 4. Unique source docs → regex for search ──
(defterm issue-docs (scope ops (list unique (list filter (project issue-ev-docs)))) :origin "unique docs" :using (issue-ev-docs))
(defterm doc-regex  (scope ops (str join "|" (project issue-docs))) :origin "regex" :using (issue-docs))

; ── 5. Cross-scope search: test files referencing issue docs ──
(defterm issue-test-hits (scope search (in "test_*" (re (project doc-regex)))) :origin "test hits" :using (doc-regex))
(defterm synthetic-hits  (scope search (in "test_*" (re "generate|synthetic"))) :origin "synth hits")

; ── 6. File intersection ──
(defterm common-files
  (scope ops (list unique (and-forms
    (list get (project issue-test-hits) 1)
    (list get (project synthetic-hits) 1))))
  :origin "files matching both"
  :using (issue-test-hits synthetic-hits))

; ── 7. Per-file search via axiom (delegate defers past ops scope) ──
(defterm file-hits :origin "search hits for one file")
(axiom file-hits-rule
  (= (file-hits ?file)
     (scope search (in ?file (or (re (project doc-regex))
                                 (re "generate|synthetic")))))
  :origin "search one file"
  :using (in or re doc-regex))

; ── 8. Per-file report section ──
(defterm rs :origin "report section per file")
(axiom rs-rule
  (= (rs ?file)
     (scope ops (str format "\n── {} ──\n  {}"
       ?file
       (str join "\n  " (list get (delegate (file-hits ?file)) 4)))))
  :origin "section"
  :using (str list format join get file-hits))

; ── 9. Recurse over all files via splat ──
(defterm report-all :origin "all sections")
(axiom report-all-base (= (report-all (?file)) (rs ?file)) :origin "base")
(axiom report-all-step
  (= (report-all (?file ?...rest)) (+ (rs ?file) (report-all (?...rest))))
  :origin "step")

; ── 10. Execute ──
(defterm body (report-all (strict (project common-files))) :origin "body" :using (common-files))
body
```

Key patterns:
- `(project expr)` — resolve in parent (bench) engine before entering scope
- `(delegate expr)` — defer resolution past current scope
- `(?file ?...rest)` — splat axioms for recursive list traversal
- `(strict ...)` — force evaluation before axiom pattern matching
- `(scope ops (list get (V data) N))` — vectorized field extraction
- `(scope ops (str format ...))` — vectorized string formatting

See also `parseltongue/core/demos/` for governance pipelines, spec validation, and revenue reports.

## Bench first, grep second

This codebase is heavily covered by .pltg. The fastest path:
1. `pg-bench find`/`fuzzy` — instant structural nodes with kind + file:line
2. `pg-bench search` — full-text with provenance tracing
3. `pg-bench eval '(scope lens/screen ...)'` — structured queries
4. grep/glob — only for things outside pltg coverage

Bench is cached via Merkle trees. After first load, queries are ~2ms.
