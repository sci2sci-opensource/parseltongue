<p align="center">
  <img src="ourouborous_core.svg" width="200" alt="Ouroboros — a system that validates itself">
</p>

# Parseltongue Core

The formal language engine. No LLM dependency — pure logic, evidence grounding, consistency checking, and self-introspection.

## Rationale

LLMs hallucinate. They produce fluent, confident text that may have no basis in the source material. Traditional approaches treat this as a retrieval problem — feed the model better context and hope for the best. But even with perfect retrieval, nothing stops the model from inventing facts, misquoting sources, or drawing conclusions that don't follow from the evidence.

Parseltongue takes a different approach: instead of asking an LLM to summarize documents, we ask it to encode each of the documents as a **logic system**. Every extracted fact must cite a verbatim quote. Every conclusion must derive from stated premises. And every derivation is checked.

This gives us two things that prose summaries cannot:

1. **Hallucination detection.** Every claim traces back to a quote in a source document. If the LLM fabricates a fact, the quote verification fails — and that failure propagates automatically to every conclusion that depends on it. You don't just catch the lie; you see everything it contaminates. This also gives the user the ability to verify only the foundation — the basic facts — conclusions are guaranteed to follow from them.

2. **Cross-document consistency checking.** Speaking plainly — **we validate if the ground truth is trustable itself.** The formal system makes it possible to compute the same value via independent paths — say, a reported growth percentage vs. one calculated from absolute revenue figures in a different document. When these paths disagree, the system flags a divergence. This catches not only LLM errors, but genuine inconsistencies in the source documents.

The result is a system where the LLM does what it's good at (reading documents, identifying relevant facts, understanding relationships) while the formal engine does what LLMs are bad at (tracking provenance, checking logical consistency, propagating uncertainty).

This particular implementation has an interesting side effect — we also have a language powerful enough to express some facts about its own implementation, which is wonderful for ensuring its own correctness.

## Quick Start

```bash
pip install parseltongue-dsl
```

`llm_doc()` and a few demos are enough for an LLM to use the language effectively. The system also supports `.pltg` module files — an s-expression format loaded via `load_pltg()` with imports, namespacing, and effects (see [Module System](#module-system) below).

Register source documents, load facts with verifiable quotes, define computed terms, derive theorems, and cross-check via diffs — all in a single script:

```python
from parseltongue import System, load_source

s = System()

# Register source documents
s.register_document("Q3 Report",
    "Q3 revenue was $15M, up 15% year-over-year. "
    "Operating margin improved to 22%.")

# Load facts with evidence — quotes are verified against documents
load_source(s, """
    (fact revenue-q3 15.0
      :evidence (evidence "Q3 Report"
        :quotes ("Q3 revenue was $15M")
        :explanation "Dollar revenue figure from Q3 report"))

    (fact revenue-q3-growth 15
      :evidence (evidence "Q3 Report"
        :quotes ("up 15% year-over-year")
        :explanation "YoY growth percentage"))
""")

# Define a computed term
load_source(s, """
    (fact growth-target 10 :origin "Board memo")

    (defterm beat-target (> revenue-q3-growth growth-target)
      :origin "Derived from growth vs target")
""")

# Derive a theorem — sources are tracked
load_source(s, """
    (derive target-exceeded
      (> revenue-q3-growth growth-target)
      :using (revenue-q3-growth growth-target))
""")

# Cross-check: compute growth from absolute figures and compare
load_source(s, """
    (fact revenue-q2 210
      :evidence (evidence "Targets Memo"
        :quotes ("Q2 FY2024 actual revenue was $210M")
        :explanation "Q2 absolute revenue"))

    (fact revenue-q3-abs 230
      :evidence (evidence "Targets Memo"
        :quotes ("Q3 FY2024 actual revenue was $230M")
        :explanation "Q3 absolute revenue"))

    (defterm revenue-growth-computed
      (* (/ (- revenue-q3-abs revenue-q2) revenue-q2) 100)
      :origin "Growth recomputed from absolute figures")

    (diff growth-check
      :replace revenue-q3-growth
      :with revenue-growth-computed)
""")

# Check consistency — the diff will flag the divergence (15% vs 9.52%)
report = s.consistency()
print(report)
# Issues found:
#   - diff_divergence: revenue-q3-growth (15) != revenue-growth-computed (9.52)
#   - no_evidence: growth-target has :origin but no :evidence with quotes
```

## Mathematical Aside

> *This section is for contributors and the mathematically curious.*

Parseltongue is a formal system in the classical sense — primitives, axioms, inference rules — but with one crucial departure from traditional mathematical logic: **the axiomatic basis is not assumed, it is grounded in evidence.**

In a standard formal system (Peano arithmetic, ZFC, etc.), axioms are taken as given. You declare them and reason from there. The system's strength is measured by its proof-theoretic ordinal — how far its induction principles can reach. But the axioms themselves are unjustified within the system; you simply trust them.

Parseltongue inverts this. Every axiom, every fact, every primitive term must cite its justification — a verbatim quote from a source document. The `apples` demo illustrates this directly: Peano axioms aren't asserted as mathematical truths, they're *derived from observational field notes* ("An empty basket contains zero apples", "The order of combining does not matter"). The formal system is built *from* the documents, not imposed on them.

**Ordinals via system extension.** The system grows by extension. You can start with the built-in operators (arithmetic, logic, comparison), or define your own primitives like `zero` and `succ`, or begin from a blank state — an empty set of symbols. From whatever starting point, you (or, conveniently, an LLM) introduce axioms, derive theorems, define new terms from those theorems, then derive further. Each layer of extension builds on everything below it. This is the ordinal hierarchy — not a static ranking of entity types, but the living growth of the system as it accumulates structure. The `apples` demo builds natural number arithmetic this way: zero, then successor, then addition defined recursively, then commutativity and identity as axioms, then concrete instances derived via `:bind`. The ordinals *are* the objects the system constructs.

**Why this matters.** Each new ordinal — each new fact, term, or axiom added to the system — expands what can be proved. A bare system with only `zero` and `succ` can say nothing about addition. Once you introduce an axiom for addition identity, you can derive that `3 + 0 = 3`. Add commutativity, and you can prove `0 + 3 = 3` too. The same principle applies far beyond arithmetic: extract a revenue figure and a growth target from two business documents, and you can derive whether the target was met; add absolute quarterly figures from a third, and you can cross-check the reported percentage against one computed independently (see `demos/revenue_reports/`). Encode diagnostic sensitivity and specificity from competing medical papers, and you can detect when their claims about the same biomarker contradict each other (see `demos/biomarkers/`). Each extension unlocks derivations that were previously unreachable — and each derivation is a new opportunity for the engine to catch a contradiction. This is the core idea from Turing's *Systems of Logic Based on Ordinals* (1939): a sequence of logics, each extending the previous one by adding new axioms, can transcend the limitations of any single formal system. Parseltongue makes this practical — each document you feed it extends the system with new axioms grounded in evidence, and the engine tracks what each extension makes provable.

**Diffs as axiom consistency checks.** Axioms from different sources may contradict each other. Diffs expose this mechanically: register two independent computation paths for the same quantity, and the system replays all dependent evaluations under both assumptions. Where results diverge, the axioms (or the documents grounding them) are inconsistent. This is not a proof of consistency — Godel tells us that's impossible for sufficiently strong systems — but a practical detection mechanism that catches real-world contradictions between documents, data sources, and reported figures.

**Fabrication propagation.** When evidence fails verification (a quote not found in its cited document), the taint propagates through the language. Every theorem derived from a fabricated source inherits the flag — the grammar of derivation (`:using`, `:bind`) defines exactly which conclusions depend on which premises. The system doesn't reject fabricated claims outright; it marks them and lets you trace exactly what they contaminate through the structure of the formal language itself.

## Directive Types

Six directive types — `fact`, `axiom`, `defterm`, `derive`, `diff`, and `evidence` — split into two categories.

In addition to primary directives, the language is extensible with [custom operators](#custom-environments) and [effects](#built-in-effects).

### Symbolic Directives

Symbols are the core entity of the language. Symbolic directives introduce named symbols into the system — facts, axioms, and terms form the axiomatic base. Each can be grounded in `:evidence` with verbatim `:quotes` or a plain `:origin` string.

**`fact`** — a named value extracted from a document. Facts are the atoms of the system: concrete data points that everything else builds on. Use them for any numeric, boolean, or string value that can be quoted verbatim from a source.

```scheme
(fact revenue-q3 15.0
  :evidence (evidence "Q3 Report"
    :quotes ("Q3 revenue was $15M")
    :explanation "Dollar revenue figure from Q3 report"))
```

**`axiom`** — a parametric rule with `?`-variables. Ground statements (no `?`-variables) are rejected; use `fact` for values or `derive` for provable claims. Axioms come in two forms: **rewrite axioms** (`(= <pattern> <rhs>)`) fire automatically during evaluation — no `:bind` needed in a derive. **Non-rewrite axioms** (`implies`, `>`, etc.) require explicit `:bind` to substitute `?`-variables with concrete values. Axioms also support `?...`-prefixed splat variables that collect trailing arguments.

```scheme
;; Rewrite axiom — fires automatically during evaluation, no :bind needed
(axiom add-commutative (= (+ ?a ?b) (+ ?b ?a))
  :origin "Arithmetic axiom")

;; Non-rewrite axiom — requires explicit :bind in derive
(axiom positive-rule (> ?x 0)
  :origin "Positivity constraint")

;; Splat axiom — ?...items collects all trailing arguments
(axiom count-exists (> (+ ?...items) 0)
  :origin "All items exist if their sum is positive")
```

**`defterm`** (forward declaration) — introduces a primitive symbol with no body (like `zero` in Peano arithmetic). These are the building blocks — named concepts that exist before any computation.

```scheme
;; Primitive symbol (no body) — forward declaration
(defterm growth-target :origin "Board-set target")
```

### Computable Directives

Computable directives produce results from the symbolic base. Computed terms are evaluated on reference. Derives are evaluated at definition time — the WFF is checked against symbols in `:using`.

**`defterm`** (computed) — an expression evaluated when referenced. Use it for derived quantities like totals or growth rates. A **conditional term** uses `if` to branch.

```scheme
;; Computed — evaluated when referenced, tracks dependencies
(defterm beat-target (> revenue-q3-growth growth-target)
  :evidence (evidence "FY2024 Targets Memo"
    :quotes ("Exceeding the growth target is defined as achieving year-over-year revenue growth above the stated target percentage")
    :explanation "Definition of what it means to beat the target"))

;; Conditional — branches based on other facts/terms
(defterm bonus-amount
  (if (> revenue-q3-growth growth-target)
      (* base-salary bonus-rate) 0)
  :origin "Bonus calculation")
```

**`derive`** — a theorem proved by evaluating a WFF against existing facts, terms, and axioms. Evaluation is restricted to symbols listed in `:using`; rewrite axioms fire automatically, non-rewrite axioms require `:bind` to substitute `?`-variables. If any source has unverified evidence, the derivation inherits the fabrication taint.

```scheme
;; Direct — evaluates a WFF against facts listed in :using
(derive target-exceeded
  (> revenue-q3-growth growth-target)
  :using (revenue-q3-growth growth-target))

;; Instantiation — :bind substitutes ?-variables, then evaluates
(derive three-plus-zero add-identity
  :bind ((?n (succ (succ (succ zero)))))
  :using (add-identity succ zero))

;; Rewrite axiom in :using — fires automatically, no :bind needed
(derive morning-commutes add-commutative
  :using (add-commutative eve-morning adam-morning))
```

### Diffs

Diffs require no evidence because inconsistency between their sides is itself a system-level issue.

**`diff`** — a lazy consistency comparison between two symbols. Diffs are how the system detects contradictions: register two independent values for the same quantity, and the engine replays all dependent computations under both assumptions. Where results diverge, something is wrong — either the LLM fabricated a value, or the source documents disagree.

```scheme
(diff growth-check
  :replace revenue-q3-growth
  :with revenue-q3-growth-computed)
```

### Evidence

Evidence is a first-class citizen and is directly used by the engine and grammar.

**`evidence`** is a structured provenance attached to symbolic directives. Evidence links a claim to a verbatim quote from a registered source document.

```scheme
;; Structured evidence with verifiable quotes
(evidence "Q3 Report"
  :quotes ("Q3 revenue was $15M")
  :explanation "Dollar revenue figure from Q3 report")

;; Plain string origin — flagged as unverified, useful for hypotheticals
;; (used via :origin instead of :evidence)
```

## Execution Engine

The engine evaluates s-expressions left-to-right, applying rewrite axioms up to a depth limit of 100, with an `=`-rewrite fallback for structural equality. Three special forms are handled directly by the engine:

| Form | Behavior |
|---|---|
| `if` | `(if cond then else)` — evaluates condition, returns `then` or `else` branch |
| `let` | `(let ((x 1) (y 2)) body)` — binds local variables, evaluates body in extended env |
| `quote` | `(quote expr)` — returns expression unevaluated |

The `Engine` constructor accepts two behavioral flags:

- **`strict_derive`** (default `True`) — when enabled, `derive` evaluation is restricted to symbols listed in `:using`. Only those facts, terms, and axioms are visible during evaluation. When disabled, all symbols in the environment are accessible (legacy mode).
- **`overridable`** (default `False`) — when disabled, redefining an existing fact raises an error. Enable to allow fact redefinition without calling `retract()` first.

### Evidence Grounding

The engine automatically performs evidence grounding when supplied an `evidence` directive, verifying `:quotes` against the documents loaded in the engine's document store. An optional `:explanation` provides human-readable context. Statements can also use a plain `:origin` string or no evidence at all:

```scheme
;; Grounded — quote verified against registered document
(fact revenue-q3 15.0
    :evidence (evidence "Q3 Report"
      :quotes ("Q3 revenue was $15M")
      :explanation "Dollar revenue figure from Q3 report"))

;; Ungrounded — flagged as unverified, useful for hypotheticals
(fact growth-target 0.1 :origin "Management memo, not digitised")

;; No evidence at all — consistency report will flag it
(fact adjustment 0.5)
```

Statements without evidence can be verified after the fact via `system.verify_manual("adjustment")` in Python or `(verify-manual adjustment)` in `.pltg` files — useful for human-in-the-loop workflows where an analyst confirms a value that has no document source.

**Fabrication propagation**: if a fact's evidence is unverified, any theorem derived from it is automatically marked as a potential fabrication. This taint propagates through derivation chains.

```python
# Check what went wrong
report = s.consistency()
for issue in report.issues:
    print(issue.type, issue.items)

# Trace evidence back to source
provenance = s.provenance("target-exceeded")
```

### Quote Verification

The engine is aware of the documents, and when a document is registered, it is normalized and indexed into an inverted word-position index (`DocumentIndex`). Each word maps to its character positions in the normalized text, so quote lookup is a candidate-set intersection rather than a linear scan. This makes verification fast even for very large document collections.

```python
from parseltongue.core.quote_verifier import QuoteVerifier

document_text = "Very big doc with Q3 revenue..."
v = QuoteVerifier(confidence_threshold=0.7)
result = v.verify_quote(document_text, "Q3 revenue was $15M")
# result: {verified: True, confidence: {score: 0.95, level: "high"}, original_position: 0, context: {...}}
```

Both the document and the quote pass through a six-step normalization pipeline (case, lists, hyphenation, punctuation, stopwords, whitespace) before matching. The verifier handles PDF artifacts, line-break hyphens, formatted numbers (`$150,000`), dotted identifiers (`parseltongue.core`), and OCR noise. A space-collapsed fallback catches cases where source documents split words across lines.

Not all normalizations are equal. Light normalizations — missing punctuation, collapsed whitespace, case differences — receive small confidence penalties. Removing semantically meaningful words (stopwords that carry meaning like "not", "all", "never") receives a heavy penalty by default, because changing those words changes the meaning of the quote. The result is a confidence score with a binary threshold for pass/fail.

The quote verifier is extensible: custom normalizers, fuzzy matchers, and custom tokenizers can be plugged in for domain-specific document formats.

### Consistency Checking

`engine.consistency()` returns a `ConsistencyReport` with three layers — evidence grounding, fabrication propagation, and diff agreement. It detects:

| Issue Type | Meaning |
|---|---|
| `unverified_evidence` | Quote not found in the registered document |
| `no_evidence` | Statement has no evidence at all |
| `potential_fabrication` | Theorem depends on unverified evidence |
| `diff_divergence` | Downstream terms diverge when swapping one value for another |
| `diff_value_divergence` | The two values in a diff disagree directly |

Diffs are the primary mechanism for cross-validation. Register a diff, and the system automatically checks whether swapping one value for another causes dependent terms to change.

```python
report = engine.consistency()
print(report.consistent)  # True / False

for issue in report.issues:
    print(issue.type, issue.items)
# e.g. "diff_value_divergence" ["revenue-check"]

# In .pltg files:
# (consistency)        — print report, return True
# (consistency :raise) — print report, raise on inconsistency
# (consistency :bool)  — return True/False without printing
# (consistency :report) — return the ConsistencyReport object
```

### Environments

The `Engine` does not hardcode any operators. It takes an `env` dict at construction — a mapping from `Symbol` to callable. The `env` dict can contain both operators and effects as callables. The engine itself makes no distinction between them — it just evaluates callables from `env`. The pure/impure split is a `System`-level convention.

This is how you build domain-specific languages: pass only the operators you need, introduce your own primitives as facts and forward-declared terms, state your domain axioms with evidence, and let the engine handle consistency and provenance. The language can support anything symbolic representation allows — any base environment for any use case of any domain.

#### Operators

Operators are **pure** — they compute a value from their arguments without access to the `System` or the engine's internal state. They are plain Python callables registered in the `env` dict:

```python
from parseltongue.core.engine import Engine
from parseltongue.core.atoms import Symbol
import operator

# Introduce a custom operator — just a callable, no system access
e = Engine(env={Symbol('+'): operator.add, Symbol('double'): lambda x: x * 2})
e.evaluate([Symbol('double'), 21])  # 42
```

#### Effects

Effects are **impure** — they receive the `System` as their first argument and can read or modify it. The `System` constructor wraps each effect callable so that `system` is auto-injected as the first argument before the engine calls it. From the engine's perspective, it's just another callable in `env`.

When the engine encounters an unrecognized top-level s-expression, it evaluates it — if the head resolves to a callable in `env`, the effect fires. Effects execute side effects (importing modules, loading documents, printing values) rather than building the formal system.

```python
from parseltongue.core.system import System

def my_log_effect(system, *args):
    """Effect receives the System — can inspect or modify it."""
    print("[LOG]", *args)
    system.engine.set_fact("log-called", True, "side effect")

s = System(effects={"log": my_log_effect})
```

See [Built-in Effects](#built-in-effects) for the full list.

## System

The `System` class composes `Engine` with default operators, effect injection, serialization, and introspection. It is the standard entry point for building and querying a Parseltongue logic system from Python. A `System()` created with no arguments is fully effect-free — it has only pure operators, no side effects. Effects are only present when explicitly passed via `effects=`.

### Core Interface

System exposes the full engine API — facts, axioms, theorems, terms, diffs, and documents — as properties delegating to the underlying `Engine`. It also provides higher-level methods for introspection:

```python
from parseltongue.core.system import System

s = System()
s.set_fact("revenue", 15.0, "Q3 report")
s.introduce_axiom("growth", [Symbol("implies"), ...], ...)
s.derive("result", wff, using=[...])

# Lookup
s.facts["revenue"]       # Fact object
s.theorems["result"]     # Theorem object

# Introspection
s.provenance("result")   # full derivation chain with evidence
s.state()                # human-readable summary
s.doc()                  # operator/directive documentation

# Serialization
data = s.to_dict()       # serialize to plain dict
s2 = System.from_dict(data)  # restore from dict

# Load .pltg source directly into a System
from parseltongue.core.system import load_source
load_source(s, '(fact x 42 :origin "inline")')
```

`provenance()` walks all five stores — facts, axioms, terms, theorems, and diffs — and returns a nested dict. For theorems, it recurses through the derivation chain, expanding each dependency's provenance.

### Default Environment

By default, `System` loads `DEFAULT_OPERATORS` from `default_system_settings` — 15 operators across three categories:

**Arithmetic** (5): `+`, `-`, `*`, `/`, `mod`
**Comparison** (6): `>`, `<`, `>=`, `<=`, `=`, `!=`
**Logic** (4): `and`, `or`, `not`, `implies`

The `ENGINE_DOCS` dictionary provides structured documentation for each operator (category, description, example, expected result), which `system.doc()` renders into a human-readable reference. The `docs=` parameter controls what `system.doc()` returns — pass a custom dict to replace the default documentation.

```python
# Override defaults
s = System(initial_env={Symbol("+"): operator.add})  # minimal
s = System(initial_env={})  # blank slate
s = System(docs={})  # no built-in documentation
```

## Demos

11 demos covering the full feature set. Each is a standalone script:

**Apples** ([`demos/apples/`](demos/apples/)) — Peano arithmetic grounded in observational field notes. Introduces primitive symbols (zero, successor), states axioms with `:evidence`, and derives theorems via `:bind` instantiation.

**Apples (.pltg)** ([`demos/apples_pltg/`](demos/apples_pltg/)) — The same apple arithmetic demo, written as a `.pltg` module file instead of Python.

**Revenue Reports** ([`demos/revenue_reports/`](demos/revenue_reports/)) — Company performance analysis from Q3 reports, targets memos, and bonus policy documents. Shows quote verification, fabrication propagation, diffs, and manual override.

**Biomarkers** ([`demos/biomarkers/`](demos/biomarkers/)) — Diagnostic marker analysis from competing medical papers. Encodes sensitivity, specificity, and clinical claims, then cross-checks for contradictions between studies.

**Code Check** ([`demos/code_check/`](demos/code_check/)) — Code implementation checks against documented contracts.

**Doc Validation** ([`demos/doc_validation/`](demos/doc_validation/)) — Documentation validation against source code.

**Spec Validation** ([`demos/spec_validation/`](demos/spec_validation/)) — Code-specification cross-validation with diff-based divergence detection.

**Extensibility** ([`demos/extensibility/`](demos/extensibility/)) — System extensibility via custom effects.

**Self-Healing** ([`demos/self_healing/`](demos/self_healing/)) — Self-healing probes via effects that detect and recover from inconsistencies.

**Deferred (.pltg)** ([`demos/deferred_pltg/`](demos/deferred_pltg/)) — `run-on-entry` — deferred directives that only fire for the main file.

**Entry Mocks (.pltg)** ([`demos/entry_mocks_pltg/`](demos/entry_mocks_pltg/)) — `run-on-entry` as a self-contained unit test with `let` and mocks.

```bash
# Run any demo, e.g.:
python -m parseltongue.core.demos.apples.demo
python -m parseltongue.core.demos.revenue_reports.demo
python -m parseltongue.core.demos.biomarkers.demo
```

## Module System

Parseltongue programs can be split across multiple `.pltg` files using the built-in module system. The `Loader` class handles import resolution, circular import detection, per-module namespacing, and runtime context.

### Loading `.pltg` Files

```python
from parseltongue import load_pltg

# Load a .pltg file — returns a fully-loaded System
system = load_pltg("path/to/main.pltg")
```

Or for more control:

```python
from parseltongue.core.loader import Loader

loader = Loader()
system = loader.load_main("path/to/main.pltg", effects=custom_effects)
```

### Built-in Effects

The loader provides 7 built-in effects available in any `.pltg` file:

| Effect | Syntax | Description |
|---|---|---|
| `import` | `(import (quote module.name))` | Import another `.pltg` module |
| `run-on-entry` | `(run-on-entry (quote (directive ...)))` | Execute directives only when file is the main entry point |
| `load-document` | `(load-document "name" "relative/path.txt")` | Register a source document for evidence grounding |
| `context` | `(context :file)` | Access per-module context (`:file`, `:dir`, `:name`, `:main`) |
| `print` | `(print "label" value ...)` | Print computed values from the system |
| `consistency` | `(consistency)` | With no arguments, prints the report and returns True. Optional modes: `(consistency :raise)` prints and raises on inconsistency, `(consistency :bool)` returns boolean without printing, `(consistency :report)` returns the ConsistencyReport object |
| `verify-manual` | `(verify-manual name)` | Manually verify a fact, term, or axiom |

### Imports and Namespacing

Modules are resolved from dot-separated names to file paths (`utils.math` → `utils/math.pltg`). Imported definitions are automatically namespaced with their module name to prevent collisions:

```scheme
; main.pltg
(import (quote lib))
; lib.pltg defines (fact total 42 ...) → accessible as lib.total
(print "Library total:" lib.total)
```

Circular imports are detected and raise an error. Duplicate imports are skipped.

### Context

Each loaded file gets an immutable `ModuleContext` following an onion model — inner modules link to the outer loader context. Context keys are namespaced per-module so `(context :file)` in `lib.pltg` resolves to the library's file path, not the main file's.

### Local Aliasing

Modules can create local aliases for namespaced symbols using `defterm`. This avoids repeating the full namespace in expressions:

```scheme
(import (quote src.primitives))
(defterm = src.primitives.= :origin "import")
(defterm + src.primitives.+ :origin "import")

; Now use short names in axioms
(axiom add-comm (= (+ ?a ?b) (+ ?b ?a)) :origin "commutativity")
```

### Lazy Evaluation

All `defterm` definitions are lazy — the body expression is stored unevaluated and resolved only when the term is referenced. This means bare aliases like `(defterm x some-symbol)` work without a `quote` wrapper; the target is resolved at use time, not definition time.

### Forward-Declared Primitives

A `defterm` with no body introduces a forward-declared primitive symbol. These primitives are available to any module that imports the defining module:

```scheme
; primitives.pltg
(defterm zero :origin "Peano base case")
(defterm succ :origin "Peano successor")

; afternoon.pltg — uses primitives without re-importing
(import (quote primitives))
(derive three-exists (= (succ (succ (succ primitives.zero))) (succ (succ (succ primitives.zero))))
  :using (primitives.zero primitives.succ))
```

### Import Chains

Imports are transitive through the module graph. If `demo` imports `app` and `app` imports `lib`, then all of `lib`'s namespaced definitions are accessible from `demo`:

```scheme
; lib.pltg:   (fact base-value 1 ...)
; app.pltg:   (import (quote lib))   → lib.base-value accessible
; demo.pltg:  (import (quote app))   → app.lib.base-value accessible
```

### Cross-Module Bind

Axioms defined in one module can be instantiated with `:bind` using terms from another module. The namespaces mix freely:

```scheme
; math.pltg defines (axiom add-identity ...)
; main.pltg:
(import (quote math))
(derive result math.add-identity
  :bind ((?n my-local-term))
  :using (math.add-identity my-local-term))
```

### run-on-entry Gating

`run-on-entry` directives execute only when the file is the main entry point. When a module is imported, its `run-on-entry` blocks are skipped — this prevents side effects from firing during import:

```scheme
(fact data 42 :origin "base data")
(run-on-entry (quote
  (derive sanity-check (= data 42) :using (data))))
; On import: only 'data' is loaded. The derive is skipped.
```

### let-mock Unit Testing

Combine `run-on-entry` with `let` to create self-contained unit tests that mock dependencies:

```scheme
(run-on-entry (quote
  (let ((mock-value 0))
    (derive test-passes (= mock-value 0) :using (mock-value)))))
```

This pattern keeps test assertions inside the module but only runs them when the file is executed directly.

## Packaging

The installed package ships `.pltg` module files and `.txt` resource documents alongside Python code via `package-data`. This ensures that demos, validation modules, and the self-validation consistency test all work from an installed package. The `parseltongue/core/tests` directory is included in pytest `testpaths` so that the consistency test runs in CI.

## Running Tests

```bash
pytest parseltongue/core/tests/ -v
```

## Acknowledgments

Alan Turing — *On Computable Numbers* (1936), *Systems of Logic Based on Ordinals* (1939). For inspiration, formalisation, and the main principles of this work.

Kurt Godel — incompleteness theorems, and the proof that no sufficiently powerful system can guarantee its own consistency. Without him we wouldn't know where to stop.

Eliezer Yudkowsky — for the hint about the language and the name:

> "There is a simple answer, and I would have enforced it upon you in any case. ***Ssnakes can't lie.*** And since I have a tremendous distaste for stupidity, I suggest you do not say anything like 'What do you mean?' You are smarter than that, and I do not have time for such conversations as ordinary people inflict on one another."
>
> Harry swallowed. Snakes can't lie. "***Two pluss two equalss four.***" Harry had tried to say that two plus two equalled three, and the word four had slipped out instead.
