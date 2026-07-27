---
name: parseltongue-bench
alias: kung-fu
description: Working with Parseltongue pg-bench — a persistent inspection daemon for .pltg formal logic files. Use when the user asks to analyze, validate, or inspect documents, codebases, or datasets using grounded formal logic. Covers daemon lifecycle, search engine, layered derivation (axioms → facts → derivation → aggregation → final diff), document extraction, visualization, and hologram comparison.
---

# Parseltongue pg-bench

> **GROUND TRUTH RULE — read this first.**
> Every document you analyze MUST be prepared as ground truth before any .pltg work begins.
> **Direct download only** — fetch the actual webpage, PDF, or file and convert to txt/md.
> **No summaries.** No "intelligent processing." No paraphrasing. No LLM-generated descriptions of content.
> If direct download is blocked by your sandbox, search the web for how to enable it in your environment (e.g. MCP tools, browser-use, file upload instructions) and explain to the user what they need to enable. Do not silently fall back to summarization.
> If direct download is truly impossible (e.g. paywalled, requires auth), manually rewrite the content and **confirm with the user that it 100% matches the document they see** before proceeding.
> The entire point of evidence grounding is that claims trace back to real text. Fabricated or summarized source documents defeat the purpose of the system.

pg-bench is a persistent inspection daemon for `.pltg` formal logic files. It loads a parseltongue system, keeps it in memory, and serves queries over a Unix socket. The CLI (`pg`) is the client.

## Quick reference

```bash
pg start main.pltg --user "Alice" --assistant "Claude"  # start + book
pg wait --timeout 120                   # wait for load
pg status                               # check state
pg reload                               # reload after file changes
pg purge --yes                          # nuclear reset
pg screen                               # consistency screening
pg eval '(+ 1 2)'                       # evaluate expression
pg search "raise ValueError"            # full-text search
pg eval '(fmt "viz" (scope lens (find ".*")))' > viz.html  # generate visualization
```

## Daemon lifecycle

**Start** with `pg start main.pltg`. **Wait** with `pg wait`. **Check** with `pg status`. **Reload** with `pg reload` after file changes. **Purge** with `pg purge --yes` for nuclear reset.

**Book a session** with `--user` and/or `--assistant` on any start command:

```bash
pg-bench serve main.pltg --user "Alice" --assistant "Claude"
pg-bench start main.pltg --user "Alice"
pg-bench up main.pltg --assistant "Claude"
```

Booking appends a session entry to `.parseltongue-bench/logbook.jsonl` — a persistent, append-only log of who used the bench and when. Either or both flags work. The session is also available in-memory via `bench.session`.

**The logbook is CWD-relative.** `.parseltongue-bench/` is created in the current working directory. Always `cd` into the project directory before running `pg-bench` commands — this ensures the logbook, cache, and session history all live next to the project files. Running from a parent directory writes the logbook to the wrong location.

**Stop with `pg stop`, restart with `pg start --replace`.** `pg stop` asks the daemon to shut down cleanly and waits for the socket to be released; `pg start --replace` does the same and then takes its place. `pg start` refuses to run when a live daemon already serves the socket — you can never stack a second daemon by accident. `pg status --all` lists every daemon on the machine (any socket, any working directory).

**NEVER use `kill -9` or `pkill -9` on the daemon.** This skips the signal handler that cleans up the Unix socket at `~/.parseltongue/bench.sock`. If you must signal by hand, `pkill -f bench_cli` (SIGTERM) matches the daemon's process name — but prefer `pg stop`.

**If the socket is stale** (daemon died or was killed with -9): `pg start` detects it and removes it automatically. No manual `rm` needed.

**Don't restart the daemon to pick up changes.** Use `pg reload` or `pg purge --yes`.

## Project structure

Structure projects like the demos in `parseltongue/core/demos/`:

```
my-analysis/
├── main.pltg              # entry point: load documents, import modules in order
├── resources/             # source documents (txt, md, csv, code)
│   ├── raw/               # original downloads (pdf, html)
│   └── paper_clean.txt    # extracted text (via pdftotext/pandoc)
└── src/
    ├── axioms.pltg        # Layer 1: formal rules with defterm + axiom
    ├── claims.pltg        # Layer 2: per-item facts with :evidence and :quotes
    └── checks.pltg        # Layers 3-5: derivation, aggregation, final diff
```

### main.pltg pattern

```scheme
; Load source documents
(load-document "paper" "resources/paper_clean.txt")
(load-document "code"  "../path/to/source.py")

; Import in dependency order
(import (quote src.axioms))   ; Layer 1: rules
(import (quote src.claims))   ; Layer 2: facts
(import (quote src.checks))   ; Layers 3-5: derivation chain
```

Import order matters — axioms must load before claims, claims before checks. `main.pltg` is the orchestrator.

**CRITICAL**: `load-document` takes a path to an actual file on disk. Never fabricate inline document content — parseltongue is designed to ground claims in real files.

**Canonical examples** are distributed with the library in `parseltongue/core/demos/`. Study them before building your own projects — especially `data_governance_pltg/`, which demonstrates the full pattern: policy axioms with grounded quotes, per-item compliance predicates, variadic reductions with splat axioms, a checker that discovers entities from raw documents and fans out compliance checks, and a manifest that ties everything together. It's the reference architecture for complex multi-layer analyses.

## Writing grounded directives

Parseltongue has three main directive types. Each has a different relationship to evidence:

### Facts — data from source documents

**Use `:evidence` with `:quotes` whenever possible.** The quote verifier checks that quoted text actually appears in the registered document.

```scheme
(fact breast-early-surv 98
  :evidence (evidence "paper"
    :quotes ("5-year survival rate of 98%")
    :explanation "breast cancer detected in localized form"))
```

Use `:origin` only for genuinely ungrounded claims, or to record **missing data** (which is itself a finding):

```scheme
(fact breast-detect-rate false
  :origin "paper provides NO early detection rate for breast cancer")
```

### Axioms — formal rules from the source document's logic

Axioms need a `defterm` declaration before the `axiom` rule. Both should be grounded:

```scheme
(defterm treatable
  :evidence (evidence "paper"
    :quotes ("More than 7 out of 10 children are cured")
    :explanation "treatability predicate — survival exceeds threshold"))

(axiom treatable-rule
  (= (treatable ?early-survival) (> ?early-survival 70))
  :evidence (evidence "paper"
    :quotes ("More than 7 out of 10 children are cured")
    :explanation "70% threshold from the paper's own benchmark"))
```

### Derived terms — computed via axiom application

Derivations use `derive` with `:using` to apply axioms. `:using` controls which axioms are in scope during evaluation — keep it **minimal** (only the axioms the derive actually needs, deps expand transitively):

```scheme
(derive breast-treatable (treatable src.claims.breast-early-surv)
  :using (src.axioms.treatable-rule))

(derive breast-curable (curable breast-treatable breast-detectable)
  :using (src.axioms.curability-rule))
```

Use `defterm` sparingly — for genuine definitions, aliases, or aggregation conjunctions. Don't use `defterm` as a substitute for `derive` when applying axioms.

**CRITICAL about `:using`**: It controls which axioms are in scope during rewrite-based evaluation. Keep it **minimal** — only the axioms the derive actually needs. Adding unnecessary axioms causes incorrect structural rewrites: an axiom you didn't intend to fire will pattern-match your intermediate expressions and corrupt evaluation. Deps expand transitively, so you never need to list indirect deps.

## Using the search engine

**Index directories first**, then use `pg search` to find exact quotes for evidence blocks.

```bash
# Index the codebase you're studying
pg index ../parseltongue/core

# Index your own project resources
pg index resources

# Index your own src modules
pg index src
```

**IMPORTANT**: After indexing new directories for the first time, use `--force` if content doesn't appear in search results: `pg index resources --force`. Indexing is additive across directories, but newly added files may need a forced re-read.

**CAUTION**: Each `pg index` call replaces the index for files with colliding relative paths. If `resources/` has `data.txt` and `src/` also has `data.txt`, the last-indexed wins. Keep filenames unique across indexed directories, or index a single parent directory.

### Search syntax

```bash
# Literal phrase
pg search "class Silence"

# Document filter (exact filename from index)
pg search '(in "atoms.py" "class Silence")'

# Set operations
pg search '(and "import" "quote")'
pg search '(or "raise ValueError" "raise Key")'
pg search '(not "raise" "KeyError")'

# Proximity
pg search '(near 5 "def" "return")'

# Regex
pg search '(re "class \w+Engine")'

# Context (surrounding lines)
pg search '(context 3 "raise ValueError")'

# Count
pg search '(count (in "*.py" (re "def test_")))'

# Scope delegation
pg search '(scope lens (kind "fact"))'
pg search '(scope screen (issues))'
```

**Use search to find exact quotes for your evidence blocks.** Don't grep. Don't cat files. The search engine has ngrams, stemming, synonyms, BM25, RRF. Use it.

## Eval — expression evaluation

`pg eval` evaluates S-expressions in the bench engine with the full std library and registered scopes.

```bash
pg eval '(+ 1 2)'                                        # arithmetic
pg eval '(count (scope lens (kind "fact")))'              # count facts
pg eval '(scope screen (issues))'                         # get issues
pg eval '(> (scope search (count (re "class"))) 50)'     # cross-scope boolean
pg eval '(fmt "viz" (scope lens (find ".*")))' > viz.html # visualization
```

### Available scopes

- **lens** — structural navigation: `(kind ...)`, `(inputs ...)`, `(downstream ...)`, `(roots)`, `(focus ...)`, `(find ...)`, `(fuzzy ...)`
- **screen** (alias: diagnose, evaluation) — consistency: `(issues)`, `(warnings)`, `(danglings)`, `(loader)`, `(consistent)`, `(focus ...)`
- **search** — full-text with set ops, ranking, context expansion
- **ops** — set operations over tagged forms: `(and-forms ...)`, `(or-forms ...)`, `(count-forms ...)`
- **hologram** — after dissect/compose/stain: `(left)`, `(right)`, `(divergent)`, `(common)`, `(only N)`

Run `pg eval --help` for the complete language reference with examples.

## Screen — consistency checking

```bash
pg screen                        # summary
pg screen --what issues          # only failing diffs
pg screen --what warnings        # unverified evidence, manual verification
pg screen --what danglings       # definitions consumed by nothing
pg screen --what loader          # load errors
pg screen --what stats           # JSON breakdown
pg screen --focus "engine."      # filter to namespace
```

## Interpret — stateful REPL

```bash
pg interpret '(fact my-val 42 :origin "test")'
pg interpret '(defterm doubled (* my-val 2) :origin "derived")'
pg interpret -f setup.pltg       # load from file
pg clean                         # reset interpret scope
```

State accumulates across interpret calls. Does not affect eval scope.

## Visualization

Generate self-contained interactive HTML with D3 force graph, cards, search, kind filters, and evidence panel:

```bash
pg eval '(fmt "viz" (scope lens (find ".*")))' > full.html
pg eval '(fmt "viz" (scope lens (kind "fact")))' > facts.html
pg eval '(fmt "viz" (scope screen (issues)))' > issues.html
pg eval '(fmt "viz" (scope lens (focus "engine.")))' > engine.html
```

## History — time travel

```bash
pg history layers              # show layers with metadata
pg history files               # list files at current state
pg history diff                # what changed between layers
pg history diff-file NAME      # single file diff
pg history restore LAYER       # non-destructive restore (appends reverse delta)
pg history restore-file NAME LAYER
pg history compact --yes       # squash all into one base
```

## Hologram — multi-lens comparison

A hologram must be **created** before you can query it. Two approaches:

**CLI approach** — creates the hologram, registers the scope, prints the view:
```bash
pg dissect diff-name                          # diff → side-by-side hologram
pg compose name1 name2                        # N names → N lenses
pg stain term1 term2                          # runtime trace → lens per name
# Then query the registered scope:
pg eval '(scope hologram (divergent))'
pg eval '(scope hologram (left))'
```

**Inline approach** — create and query in one expression:
```bash
# Dissect inline (create hologram + return result)
pg eval '(scope hologram (dissect "my-diff-name"))'

# Dissect inline + viz
pg eval '(fmt "viz" (scope hologram (dissect "my-diff-name")))' > comparison.html

# Stain inline
pg eval '(scope hologram (dissect (stain "my-term")))'
```

You **cannot** call `(scope hologram (divergent))` without first creating a hologram via one of these methods.

## Diffs — the core diagnostic

Diffs compare two values that should agree:

```scheme
(diff my-check
  :replace expected-value
  :with actual-value)
```

Screen reports `diff_value_divergence` when they differ. This is the fundamental mechanism for cross-checking.

## Workflow for building a grounded analysis

**Don't use parseltongue as a notebook.** Floating facts and isolated diffs are not analysis — they're notes. A proper analysis has layered derivation: axioms → per-item facts → derivation → aggregation → final diff. The viz should show a connected dependency graph, not scattered islands.

### The five-layer pattern

Study `parseltongue/core/demos/data_governance_pltg/` — it's the reference architecture. Every formal analysis follows this shape:

**Layer 1: Axioms** (`src/axioms.pltg`) — Formal rules grounded in the source document. Each axiom has a `defterm` declaration followed by an `axiom` rule. The axioms define predicates that will be applied to individual items.

```scheme
; Declare the predicate
(defterm curable
  :evidence (evidence "paper"
    :quotes ("all cancers are curable if they are caught early enough")
    :explanation "curability predicate"))

; Define the rule
(axiom curability-rule
  (= (curable ?treatable ?detectable)
     (and ?treatable ?detectable))
  :evidence (evidence "paper"
    :quotes ("all cancers are curable if they are caught early enough")
    :explanation "curable requires BOTH treatment efficacy AND early detection"))
```

Axioms encode the *logic* of the domain — what curability means, what compliance requires, what thresholds apply. They come from the source document's own stated or implied rules.

**Layer 2: Per-item facts** (`src/claims.pltg`) — Raw data extracted from the source, one fact per claim, each grounded with `:evidence` and verified `:quotes`. Organized by entity (per cancer type, per dataset, per module).

```scheme
(fact breast-early-surv 98
  :evidence (evidence "paper"
    :quotes ("5-year survival rate of 98%")
    :explanation "breast cancer detected in localized form"))

(fact breast-detect-rate false
  :origin "paper provides NO early detection rate for breast cancer")
```

Note: `false` facts with `:origin` are legitimate — they record the *absence* of data, which is itself a finding.

**Layer 3: Per-item derivation** (`src/checks.pltg`) — Apply axioms to each item via `derive` with `:using`. This is where predicates meet data.

```scheme
(derive breast-treatable (treatable src.claims.breast-early-surv)
  :using (src.axioms.treatable-rule))

(derive breast-detectable (detectable-missing)
  :using (src.axioms.detectable-rule-no-data))

(derive breast-curable (curable breast-treatable breast-detectable)
  :using (src.axioms.curability-rule))
```

Also compute derived quantities — survival gaps, Bayesian expected values:

```scheme
(derive breast-gap (survival-gap src.claims.breast-early-surv src.claims.breast-stage4-surv)
  :using (src.axioms.survival-gap-rule))
```

**Layer 4: Aggregation** — Combine per-item conclusions. `defterm` is appropriate here for genuine definitions that alias or conjoin derived results:

```scheme
(defterm all-treatable (and breast-treatable colon-treatable cervical-treatable ...)
  :origin "all six pass the treatability threshold")

(defterm cancers-curable-derived all-curable
  :origin "derived from per-type analysis: 0 of 6 meet both requirements")
```

**Layer 5: Final diff** — The thesis vs the derived conclusion. This is what the whole analysis builds toward.

```scheme
(diff thesis-vs-derivation
  :replace src.claims.thesis-all-curable
  :with cancers-curable-derived)
```

The screen will report `diff_value_divergence` or `diff_contamination` depending on whether the derivation chain is fully grounded. Both are meaningful findings.

### What the screen tells you at each layer

- **Layer 2 issues**: `no_evidence` on facts with `:origin` — these are data gaps in the source document. Expected and informative.
- **Layer 3 issues**: `derive` results are grounded through their `:using` axioms. If the axioms are grounded, the derivation inherits that grounding. Ungrounded axioms propagate `no_evidence` downstream.
- **Layer 5 issues**: `diff_value_divergence` — the thesis and derivation disagree. This is the finding. `diff_contamination` — the diff depends on ungrounded derivation steps. This is epistemic honesty — "my conclusion involves interpretive choices."

### What makes a good analysis vs a notebook

**Notebook (don't do this):**
- Floating facts with no connections
- Diffs between random pairs
- No axioms — just assertions
- Viz shows isolated islands

**Proper analysis:**
- Every fact feeds into a derivation
- Every derivation applies a declared axiom
- Derivations aggregate into a conclusion
- The conclusion is diffed against the thesis
- Viz shows a connected graph from source quotes → axioms → derivations → aggregation → final diff
- The screen output tells a coherent story: what's grounded, what's interpreted, where the divergences are

### Step-by-step process

1. **Read the source document.** Identify its central thesis and its supporting evidence structure.
2. **Formalize the thesis.** What does the claim actually require? Break it into necessary conditions. Write axioms.
3. **Extract per-item facts.** For each entity the document discusses, pull the specific numbers with verified quotes.
4. **Note missing data.** Facts the document doesn't provide are findings. Record them as `(fact X false :origin "not provided")`.
5. **Apply axioms to each item.** Derive treatable/detectable/compliant/valid per entity.
6. **Aggregate.** Count how many pass, how many fail, the overall conjunction.
7. **Diff the thesis against the derivation.** This is the punchline.
8. **Screen.** The issue list IS the analysis result. Present it as such.
9. **Visualize.** The dependency graph should show the full derivation chain from source quotes to final diff.

### Bayesian computation pattern

When the source provides conditional rates, compute expected values:

```scheme
; P(survive) = P(early) * P(survive|early) + P(late) * P(survive|late)
(axiom expected-survival-rule
  (= (expected-survival ?early-rate ?early-surv ?late-surv)
     (+ (* (/ ?early-rate 100) ?early-surv)
        (* (/ (- 100 ?early-rate) 100) ?late-surv)))
  :origin "Bayesian expected survival")

; When data is incomplete, compute floor (late survival = 0)
(derive colon-expected-floor
  (expected-survival colon-detect-rate colon-early-surv 0)
  :using (expected-survival-rule))
```

Then diff the headline number against the expected value:

```scheme
(diff headline-vs-reality
  :replace colon-early-surv       ; 90% — what the paper says
  :with colon-expected-floor)      ; 35.1% — what the population faces
```

## How to use pg-bench in a conversation

pg-bench is not just a CLI tool — it's an interactive exploration instrument. When a user asks you to look at a parseltongue project or codebase, the conversation should feel like a guided lab session, not a data dump.

### First contact with a repo

When the user points you at a `.pltg` file or a parseltongue repo:

1. **Start the daemon** and wait for it to load. Report status — path, live/frozen, integrity (verified/corrupted).
2. **Run `pg screen`** immediately. This is the health check. Share the summary: how many issues, what kinds. This orients the conversation — the user sees whether the system is healthy or sick.
3. **Run `pg kinds`** to show what's in the system — how many facts, terms, theorems, diffs. This gives the user a map before diving in.
4. **Index the codebase** if the user wants to search source files. Report how many files were indexed.

Don't dump raw output. Summarize: "The system loaded clean — 42 facts, 15 diffs, 3 issues. The issues are two value divergences in the engine module and one unverified quote."

### When the user asks questions

- **"What's wrong?"** → `pg screen --what issues`. Summarize the issues in plain language, then offer to dig into specific ones.
- **"Show me the structure"** → `pg view` for the probe graph, or `pg kinds` + `pg roots` for an overview. For specific nodes: `pg view node-name` or `pg consumer node-name`.
- **"Find X in the code"** → `pg search`. Use the S-expression query language for precise searches. Show the results with context.
- **"How does X relate to Y?"** → `pg subgraph name` or `pg dissect diff-name` for side-by-side comparison. Consider generating a hologram if the user wants to compare multiple things.

### When to generate visualizations

**Generate viz HTML and present it to the user when:**

- The user asks to "see" or "visualize" the system
- There are more than ~10 nodes and text output would be overwhelming
- The user is exploring relationships between nodes (the D3 force graph helps)
- You've just run a screen and want to show which nodes are healthy vs problematic
- The user asks for an overview or map of the system
- You want to show the result of a focused query: `(fmt "viz" (scope lens (focus "engine.")))`

**Don't generate viz when:**

- The answer is a single number or boolean (`pg eval '(count ...)'`)
- The user is asking about a specific node (just `pg view name`)
- The system has only 2-3 nodes (text is clearer)
- The user is iterating quickly and doesn't need a full render each time

**Viz examples by situation:**

```bash
# "Show me everything"
pg eval '(fmt "viz" (scope lens (find ".*")))' > full.html

# "Show me just the facts"
pg eval '(fmt "viz" (scope lens (kind "fact")))' > facts.html

# "What's broken?"
pg eval '(fmt "viz" (scope screen (issues)))' > issues.html

# "Show me the engine module"
pg eval '(fmt "viz" (scope lens (focus "engine.")))' > engine.html

# "Compare these two sides of a diff" — inline hologram creation + viz
pg eval '(fmt "viz" (scope hologram (dissect "src.analysis.team-gap")))' > comparison.html
```

Save the HTML to `/mnt/user-data/outputs/` and present it with `present_files`. The viz is self-contained — interactive cards, D3 graph, search, filters, evidence panel. Let the user explore it.

### Building an analysis together

When the user wants to build a formal analysis of something (a document, a codebase, a dataset):

1. **Read the source first.** Understand the thesis, identify what it claims, what evidence it provides, and what's missing. This shapes everything.
2. **Set up the project structure** — `main.pltg`, `resources/`, `src/`. Extract text from any uploaded documents using `pdftotext`/`pandoc`.
3. **Write axioms first** (`src/axioms.pltg`). Formalize the thesis — what does the claim actually require? What predicates, what thresholds, what logical structure? Share this with the user: "The paper claims curability. I'm formalizing that as requiring both treatability AND detectability."
4. **Extract per-item facts** (`src/claims.pltg`). Use `pg search` to find exact quotes. Record missing data as `(fact X false :origin "not provided")`. These gaps are findings.
5. **Build the derivation chain** (`src/checks.pltg`). Apply axioms to each item. Aggregate. Diff thesis vs derivation.
6. **Reload and screen at each step.** The issue count tells the story — what's grounded, what's not, where the divergences are. Share this with the user at each milestone.
7. **Visualize the final result.** The graph should show a connected chain from source quotes through axioms to the final diff — not floating islands. The hologram dissection of the final diff shows both sides: what the thesis claims vs what the derivation found.

### Presenting results

After the analysis is complete, summarize by following the derivation chain:

1. **State the thesis** as the source document presents it.
2. **State the formalization** — what does the thesis require? What axioms did you define?
3. **Walk through the layers** — treatability established for N/M, detectability for N/M, etc. Use the actual numbers.
4. **State the divergence** — where the derivation disagrees with the thesis, and why.
5. **Note what the source itself says** — does the conclusion agree with its own thesis, or with the derivation?
6. **Be explicit about the interpretive boundary** — which steps are grounded in quotes, which are your axiom choices. The screen output makes this visible: grounded facts verified, derivation flagged as `no_evidence`, diffs flagged the divergences.

The summary should feel like a proof walkthrough, not an opinion piece. Let the structure do the talking.

### Tone and framing

pg-bench is a laboratory instrument. Frame it that way:

- "Let me screen the system" not "let me test it"
- "The system flags this as ungrounded" not "this is wrong"
- "The diff found a divergence" not "there's a bug"
- "These claims verified against the source" not "these are correct"

The system doesn't judge truth — it judges grounding. A fact with `:origin` might be perfectly true but the system can't verify it. That's not failure, it's honest epistemic humility. Explain this distinction when the user first encounters `no_evidence` flags.

## Extracting text from uploaded documents

When the user provides a PDF, DOCX, PPTX, or other document, extract text and save it as a resource file before registering it.

**Available tools:**
- `pdftotext` — PDF to plain text (installed)
- `pandoc` — converts between most formats: docx, pptx, html, markdown, epub, rst (installed)
- `libreoffice --headless` — Office format conversion (installed)

**Workflow:**

```bash
# PDF
pdftotext document.pdf resources/document.txt

# DOCX / PPTX / HTML → plain text via pandoc
pandoc -f docx -t plain document.docx -o resources/document.txt
pandoc -f html -t plain page.html -o resources/document.txt

# Fetched web page (may need cleaning)
curl -L -s -o resources/raw/page.html "https://..."
pandoc -f html -t plain resources/raw/page.html > resources/page_clean.txt
```

**Then in main.pltg:**
```scheme
(load-document "paper" "resources/document.txt")
```

**Key pattern:** Save raw downloads to `resources/raw/`, cleaned text to `resources/`. Register only the cleaned version. Index `resources/` so you can `pg search` for exact quotes to use in evidence blocks.

## Common mistakes

- **Using parseltongue as a notebook** → floating facts, isolated diffs, no axioms, no derivation chain. The viz will show disconnected islands. Build layered: axioms → facts → derivation → aggregation → final diff. Study the `data_governance_pltg` demo.
- **Skipping axioms** → jumping straight to facts and diffs means no formal structure. The axioms define what the analysis IS. Write them first.
- **Not recording missing data** → a fact the source doesn't provide is itself a finding. Record it as `(fact X false :origin "not provided")`. Five missing detection rates IS the analysis result.
- **`kill -9` on daemon** → stale socket, connection errors. Use SIGTERM or `pg reload`.
- **Using grep instead of `pg search`** → the search engine is indexed with RRF ranking. Use it.
- **`:origin` instead of `:evidence`** → system flags every claim as `no_evidence`. Ground your facts.
- **Fabricating inline documents** → `load-document` needs actual files. The language prevents lying.
- **Restarting daemon instead of `pg reload`** → unnecessary. The daemon is designed to persist.
- **Not reading `pg eval --help`** → it's a full language reference. Read it first.
- **Not `--force` after first index of new files** → content may not appear in search until forced.
- **Summarizing or paraphrasing source documents** → the system quotes exact text. If your "document" is an LLM summary, every quote verification will fail or be meaningless. Always use direct file downloads converted to txt/md. If your sandbox blocks downloads, search for how to enable it (MCP tools, browser-use, file upload) and tell the user what to enable — do not silently fall back to summaries. Only rewrite content as a last resort, and confirm with the user it matches exactly.

## Taint tracking

Every visualization view shows taint status — which nodes are trusted and which aren't. Taint is computed server-side in Python and embedded as `TAINT_DATA` in the HTML. All views (cards, layers, graph, detail panel, notebook) consume the same pre-computed result.

### What gets tainted

A node is a **taint source** if:
- It has no evidence at all
- Its evidence has a status other than `verified`, `derived`, or `manual`
- It was manually verified but the signature doesn't match a known session participant
- It was manually verified with no signature
- It was manually verified but there's no logbook (no session was booked)

A node is **tainted** (propagated) if any of its inputs are taint sources or tainted themselves. Propagation is transitive through the full dependency graph.

### Session booking drives taint

The logbook (`.parseltongue-bench/logbook.jsonl`) records who used the bench. The taint predicate checks manual verification signatures against known participants from the logbook.

**Without a booked session, ALL manually verified items are tainted.** Always book:

```bash
pg start main.pltg --user "Alice" --assistant "Claude"
pg-bench render notebook.pgmd --user "Alice" --assistant "Claude" -o out.html
```

### Visual treatment

| Context | Taint source | Tainted (propagated) | Clean |
|---------|-------------|---------------------|-------|
| Cards | Red border, "taint source" tag | Yellow dashed border, "tainted" tag | Normal |
| Layers pills | Red solid stroke | Yellow dashed stroke | Kind color |
| Graph nodes | Red stroke | Yellow stroke | Kind color |
| Detail panel | Red "Taint source" section with reason | Yellow "Tainted" section with reason | No section |
| Notebook margin pills | Red border, ✖ icon | Yellow dashed border, ⚠ icon | No border |
| Notebook inline refs | Red wavy underline | Yellow dashed underline | Normal |

Taint reasons explain why: "no evidence", "unverified (unknown)", "manually verified (no session log)", "signed by 'X' — not a known session participant", or "depends on tainted: Y".

### verify-manual and taint

`verify-manual` signs an axiom or fact as reviewed. The signature must match a logbook participant for the item to be clean:

```scheme
;; Clean — "Claude" is a known assistant in the logbook
(verify-manual (quote my-axiom) "Claude")

;; Tainted — no signature
(verify-manual (quote my-axiom))

;; Tainted — "Unknown Intern" not in the logbook
(verify-manual (quote my-axiom) "Unknown Intern")
```

Separate review files (`review-*.pltg`) contain post-session verifications. See `pg-bench learn to-connect` for the full verification protocol.

## See also

- `pg-bench learn to-connect` — writing .pgmd notebooks (literate analysis with prose + pltg blocks, rendered to HTML)