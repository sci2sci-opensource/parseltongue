<p align="center">
  <img src="https://raw.githubusercontent.com/sci2sci-opensource/parseltongue/HEAD/parseltongue.svg" alt="Parseltongue" width="200">
</p>

# Parseltongue

[![CI](https://github.com/sci2sci-opensource/parseltongue/actions/workflows/ci.yml/badge.svg)](https://github.com/sci2sci-opensource/parseltongue/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/parseltongue-dsl)](https://pypi.org/project/parseltongue-dsl/)
[![Python](https://img.shields.io/pypi/pyversions/parseltongue-dsl)](https://pypi.org/project/parseltongue-dsl/)
[![License](https://img.shields.io/github/license/sci2sci-opensource/parseltongue)](https://github.com/sci2sci-opensource/parseltongue/blob/main/LICENSE)

A DSL for systems that refuse to speak falsehood.

## Rationale - Why?

LLMs hallucinate. They produce fluent, confident text that may have no basis in the source material. Traditional approaches treat this as a retrieval problem — feed the model better context and hope for the best. But even with perfect retrieval, nothing stops the model from inventing facts, misquoting sources, or drawing conclusions that don't follow from the evidence.

Parseltongue takes a different approach: instead of asking an LLM to summarize documents, we ask it to encode each of the documents as a **logic system**. Every extracted fact must cite a verbatim quote. Every conclusion must derive from stated premises. And every derivation is checked.

This gives us two things that prose summaries cannot:

1. **Hallucination detection.** Every claim traces back to a quote in a source document. If the LLM fabricates a fact, the quote verification fails — and that failure propagates automatically to every conclusion that depends on it. You don't just catch the lie; you see everything it contaminates. This also gives the user the ability to verify only the foundation — the basic facts — conclusions are guaranteed to follow from them.

2. **Cross-document consistency checking.** Speaking plainly — **we validate if the ground truth is trustable itself.** The formal system makes it possible to compute the same value via independent paths — say, a reported growth percentage vs. one calculated from absolute revenue figures in a different document. When these paths disagree, the system flags a divergence. This catches not only LLM errors, but genuine inconsistencies in the source documents.

The result is a system where the LLM does what it's good at (reading documents, identifying relevant facts, understanding relationships) while the formal engine does what LLMs are bad at (tracking provenance, checking logical consistency, propagating uncertainty).

## Quick Start

The main way to use Parseltongue is through the LLM pipeline. You give it documents and a question; it builds a formal logic system, cross-validates it, and returns a grounded answer where every claim links back to a verbatim quote. The truth-checking, fabrication detection, and consistency verification are all handled by the internal DSL machinery in `core` — you don't need to write any s-expressions yourself.

```bash
pip install parseltongue-dsl[llm]
export OPENROUTER_API_KEY=sk-...
```

```python
from parseltongue import System, Pipeline
from parseltongue.llm.openrouter import OpenRouterProvider


system = System(overridable=True)
# overridable=True lets statements overwrite each other (useful for LLM pipelines
# that may revise facts across passes). Default is False — statements are immutable
# and must be explicitly retracted before redefining.
provider = OpenRouterProvider()  # reads OPENROUTER_API_KEY from .env

pipeline = Pipeline(system, provider)
pipeline.add_document("Q3 Report", path="q3_report.txt")
pipeline.add_document("Targets Memo", path="targets_memo.txt")
pipeline.add_document("Bonus Policy", text="Bonus is 20% of base salary...")

result = pipeline.run("Did we beat the growth target? What is the bonus?")
```

See the [full demo output](parseltongue/llm/demos/revenue/demo_example_output.md) for a complete example of what the pipeline produces.

For example, `result.output.markdown` might contain:

```markdown
> **Inconsistency detected:** The reported growth of 15% does not match
> the 9.52% computed from absolute revenue figures [[diff:growth-check]].
```

The `[[diff:growth-check]]` reference resolves to a `DiffResult`:

```
name:        growth-check
replace:     revenue-q3-growth
with:        revenue-growth-from-absolutes
value_a:     15
value_b:     9.523809523809524
divergences:
  beat-target:   [True, False]
  bonus-amount:  [30000.0, 0]
```

The diff tells you not just that two values disagree, but exactly which downstream conclusions flip as a result — here, whether the target was beaten and whether a $30,000 bonus is paid.

You can drill into the full provenance of the diff via `system.provenance("growth-check")`:

```json
{
  "name": "growth-check",
  "type": "diff",
  "replace": "revenue-q3-growth",
  "with": "revenue-growth-from-absolutes",
  "value_a": 15,
  "value_b": 9.52,
  "divergences": {
    "beat-target": [true, false],
    "bonus-amount": [30000.0, 0]
  },
  "provenance_a": {
    "name": "revenue-q3-growth",
    "type": "fact",
    "origin": {
      "document": "Q3 Report",
      "quotes": ["up 15% year-over-year"],
      "verified": true,
      "grounded": true
    }
  },
  "provenance_b (simplified — in reality each revenue-* fact would have its own quotes)": {
    "name": "revenue-growth-from-absolutes",
    "type": "term",
    "definition": "(* (/ (- revenue-q3-abs revenue-q2) revenue-q2) 100)",
    "origin": {
      "document": "Targets Memo",
      "quotes": ["Q2 FY2024 actual revenue was $210M.", "Q3 FY2024 actual revenue was $230M."], 
      "verified": true,
      "grounded": true
    }
  }
}
```

Each side traces back to its source: one to a verified quote in the Q3 Report, the other to a formula over audited figures from the Targets Memo.

What you get back:

- **`result.output.markdown`** — a human-readable report where every claim is tagged with `[[type:name]]` references to the formal system. Each reference resolves to a full JSON tree: the derivation chain, the verbatim source quotes, and how trustworthy the claim is within the formal system (verified, unverified, or fabrication). This lets you click through any statement in the report and quickly validate it back to the source documents. If the documents contradict each other, the report opens with a warning.
- **`result.output.references`** — the resolved references as a list: each tag mapped to its value, provenance chain, and source quotes.
- **`result.output.consistency`** — a consistency report listing unverified evidence, fabrication chains, and diff divergences.
- **`result.system`** — the full formal system the LLM built, available for further inspection via `system.provenance(name)`, `system.eval_diff(name)`, etc.

Under the hood, the pipeline runs four passes — extraction, blinded derivation, fact-checking, and inference. Each pass uses tool calling (`tool_choice="required"`) so the LLM outputs structured DSL, never raw prose. To add your own providers or customize the pipeline, see [LLM Pipeline — Deep Dive](#llm-pipeline--deep-dive).

```
  Documents + Query
        |
  Pass 1: Extract -----> facts, axioms, terms with :evidence
        |
  Pass 2: Derive ------> derivations and diffs (values HIDDEN)
        |
  Pass 3: Fact-Check ---> cross-validation via alternative paths + diffs
        |
  Pass 4: Answer -------> grounded markdown with [[type:name]] references
```

### Running the Demo

```bash
python -m parseltongue.llm.demos.revenue.demo
python -m parseltongue.llm.demos.revenue.demo --reasoning-tokens 8000
python -m parseltongue.llm.demos.revenue.demo --no-thinking
```

---

This section and the [LLM Pipeline — Deep Dive](#llm-pipeline--deep-dive) are everything you need to know to use Parseltongue. The following sections describe the design choices behind the system, the core language it builds on, and how to build your own optimized domain-specific language to use alongside (or instead) the default one.

## Mathematical Aside

> *This section is for contributors and the mathematically curious. It is not necessary for using Parseltongue — skip to [Core Language](#core-language) if you just want to work with the DSL directly.*

Parseltongue is a formal system in the classical sense — primitives, axioms, inference rules — but with one crucial departure from traditional mathematical logic: **the axiomatic basis is not assumed, it is grounded in evidence.**

In a standard formal system (Peano arithmetic, ZFC, etc.), axioms are taken as given. You declare them and reason from there. The system's strength is measured by its proof-theoretic ordinal — how far its induction principles can reach. But the axioms themselves are unjustified within the system; you simply trust them.

Parseltongue inverts this. Every axiom, every fact, every primitive term must cite its justification — a verbatim quote from a source document. The `apples` demo illustrates this directly: Peano axioms aren't asserted as mathematical truths, they're *derived from observational field notes* ("An empty basket contains zero apples", "The order of combining does not matter"). The formal system is built *from* the documents, not imposed on them.

**Ordinals via system extension.** The system grows by extension. You can start with the built-in operators (arithmetic, logic, comparison), or define your own primitives like `zero` and `succ`, or begin from a blank state — an empty set of symbols. From whatever starting point, you (or, conveniently, an LLM) introduce axioms, derive theorems, define new terms from those theorems, then derive further. Each layer of extension builds on everything below it. This is the ordinal hierarchy — not a static ranking of entity types, but the living growth of the system as it accumulates structure. The `apples` demo builds natural number arithmetic this way: zero, then successor, then addition defined recursively, then commutativity and identity as axioms, then concrete instances derived via `:bind`. The ordinals *are* the objects the system constructs.

**Why this matters.** Each new ordinal — each new fact, term, or axiom added to the system — expands what can be proved. A bare system with only `zero` and `succ` can say nothing about addition. Once you introduce an axiom for addition identity, you can derive that `3 + 0 = 3`. Add commutativity, and you can prove `0 + 3 = 3` too. The same principle applies far beyond arithmetic: extract a revenue figure and a growth target from two business documents, and you can derive whether the target was met; add absolute quarterly figures from a third, and you can cross-check the reported percentage against one computed independently (see `core/demos/revenue_reports/`). Encode diagnostic sensitivity and specificity from competing medical papers, and you can detect when their claims about the same biomarker contradict each other (see `core/demos/biomarkers/`). Each extension unlocks derivations that were previously unreachable — and each derivation is a new opportunity for the engine to catch a contradiction. This is the core idea from Turing's *Systems of Logic Based on Ordinals* (1939): a sequence of logics, each extending the previous one by adding new axioms, can transcend the limitations of any single formal system. Parseltongue makes this practical — each document you feed it extends the system with new axioms grounded in evidence, and the engine tracks what each extension makes provable.

**Diffs as axiom consistency checks.** Axioms from different sources may contradict each other. Diffs expose this mechanically: register two independent computation paths for the same quantity, and the system replays all dependent evaluations under both assumptions. Where results diverge, the axioms (or the documents grounding them) are inconsistent. This is not a proof of consistency — Godel tells us that's impossible for sufficiently strong systems — but a practical detection mechanism that catches real-world contradictions between documents, data sources, and reported figures.

**Fabrication propagation.** When evidence fails verification (a quote not found in its cited document), the taint propagates through the language. Every theorem derived from a fabricated source inherits the flag — the grammar of derivation (`:using`, `:bind`) defines exactly which conclusions depend on which premises. The system doesn't reject fabricated claims outright; it marks them and lets you trace exactly what they contaminate through the structure of the formal language itself.

## Core Language

The DSL in `core` is what the pipeline builds under the hood. You can also use it directly. Five directive types, each optionally grounded in `:evidence` with verbatim quotes or a plain `:origin` string.

```bash
pip install parseltongue-dsl
```

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

### Directive Types

**`fact`** — a named value extracted from a document. Facts are the atoms of the system: concrete data points that everything else builds on. Use them for any numeric, boolean, or string value that can be quoted verbatim from a source.

```scheme
(fact revenue-q3 15.0
  :evidence (evidence "Q3 Report"
    :quotes ("Q3 revenue was $15M")
    :explanation "Dollar revenue figure from Q3 report"))
```

**`axiom`** — a well-formed formula asserted as true. Axioms state relationships between facts — equalities, inequalities, logical rules. Use concrete axioms to assert something about specific facts, or parameterised axioms (with `?`-variables) to state general rules that can be instantiated later via `:bind`.

```scheme
;; Concrete — asserts something about existing facts
(axiom positive-revenue (> revenue-q3 0)
  :evidence (evidence "Q3 Report"
    :quotes ("Q3 revenue was $15M")
    :explanation "Revenue is positive"))

;; Parameterised — a reusable rule with ?-variables
(axiom add-commutative (= (+ ?a ?b) (+ ?b ?a))
  :origin "Arithmetic axiom")
```

**`defterm`** — a named concept. Terms come in three forms. A **forward declaration** introduces a primitive symbol with no body (like `zero` in Peano arithmetic). A **computed term** is an expression evaluated on reference — use it for derived quantities like totals or growth rates. A **conditional term** uses `if` to branch.

```scheme
;; Primitive symbol (no body) — the building block
(defterm zero :origin "Base case")

;; Computed — evaluated when referenced, tracks dependencies
(defterm morning-total (+ eve-morning adam-morning)
  :origin "Sum of morning picks")

;; Conditional — branches based on other facts/terms
(defterm bonus-amount
  (if (> revenue-q3-growth growth-target)
      (* base-salary bonus-rate) 0)
  :origin "Bonus calculation")
```

**`derive`** — a theorem proved from existing facts, terms, and axioms. Derivations are the inference engine: they evaluate a well-formed formula and record which sources were used. If any source has unverified evidence, the derivation inherits the fabrication taint. Use `:bind` to instantiate parameterised axioms with concrete values.

```scheme
;; Direct — evaluates a WFF against existing facts
(derive target-exceeded
  (> revenue-q3-growth growth-target)
  :using (revenue-q3-growth growth-target))

;; Instantiation — plugs concrete values into a parameterised axiom
(derive three-plus-zero add-identity
  :bind ((?n (succ (succ (succ zero)))))
  :using (add-identity))
```

**`diff`** — a lazy consistency comparison between two symbols. Diffs are how the system detects contradictions: register two independent values for the same quantity, and the engine replays all dependent computations under both assumptions. Where results diverge, something is wrong — either the LLM fabricated a value, or the source documents disagree.

```scheme
(diff growth-check
  :replace revenue-q3-growth
  :with revenue-q3-growth-computed)
```

### Evidence Grounding

Evidence is a first-class citizen. It can be attached to any foundational atom — facts, axioms, and terms:

```scheme
;; Structured evidence with verifiable quotes
(fact revenue-q3 15.0
    :evidence (evidence "Q3 Report"
      :quotes ("Q3 revenue was $15M")
      :explanation "Dollar revenue figure from Q3 report"))

;; Plain string origin — flagged as unverified, useful for hypotheticals
(fact growth-target 0.1 :origin "Management memo, not digitised")

;; No evidence at all — consistency report will flag it
(fact adjustment 0.5)
```

Statements without evidence can be verified after the fact via `system.verify_manual("adjustment")` — useful for human-in-the-loop workflows where an analyst confirms a value that has no document source.

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

The main engine is aware of the documents, and when a document is registered, it is normalized and indexed into an inverted word-position index (`DocumentIndex`). Each word maps to its character positions in the normalized text, so quote lookup is a candidate-set intersection rather than a linear scan. This makes verification fast even for very large document collections.

```python
from parseltongue.core.quote_verifier import QuoteVerifier

document_text = "Very big doc with Q3 revenue..."
v = QuoteVerifier(confidence_threshold=0.7)
result = v.verify_quote(document_text, "Q3 revenue was $15M")
# result: {verified: True, confidence: 0.95, position: 42, context: "..."}
```

Both the document and the quote pass through a six-step normalization pipeline (case, lists, hyphenation, punctuation, stopwords, whitespace) before matching. The verifier handles PDF artifacts, line-break hyphens, formatted numbers (`$150,000`), dotted identifiers (`parseltongue.core`), and OCR noise. A space-collapsed fallback catches cases where source documents split words across lines.

Not all normalizations are equal. Light normalizations — missing punctuation, collapsed whitespace, case differences — receive small confidence penalties. Removing semantically meaningful words (stopwords that carry meaning like "not", "all", "never") receives a heavy penalty by default, because changing those words changes the meaning of the quote. The result is a confidence score with a binary threshold for pass/fail.

The quote verifier is extensible: custom normalizers, fuzzy matchers, and custom tokenizers can be plugged in for domain-specific document formats.

### Custom Environments

The `System` engine does not hardcode any operators. By default it loads arithmetic, comparison, and logic into the environment, but you can replace them entirely or start from scratch. The `docs=` parameter controls what `system.doc()` returns — this is what the LLM pipeline feeds to the model so it knows which operators and directives are available.

```python
from parseltongue import System, Symbol, DEFAULT_OPERATORS, ENGINE_DOCS
import operator

# Default — all built-in operators and docs
s = System()

# Extend — add your own alongside defaults
double = Symbol('double')
s = System(
    initial_env={**DEFAULT_OPERATORS, double: lambda x: x * 2},
    docs={**ENGINE_DOCS, double: {
        'category': 'custom',
        'description': 'Doubles a value',
        'example': '(double 5)',
        'expected': '10',
    }},
)

# Minimal — only what you need
s = System(initial_env={Symbol('+'): operator.add}, docs={})

# Blank slate — build everything from primitives
s = System(initial_env={}, docs={})
```

This is how you build domain-specific languages: strip the defaults, introduce your own primitives as facts and forward-declared terms, state your domain axioms with evidence, and let the engine handle consistency and provenance.

The language can support anything you might need: probabilistic logic, temporal identifiers and relationships, pandas functions as primitives, etc. It provably does anything symbolic representation could allow — any base environment for any use case of any domain.

### Consistency Checking

`system.consistency()` returns a `ConsistencyReport` that detects:

| Issue Type | Meaning |
|---|---|
| `unverified_evidence` | Quote not found in the registered document |
| `no_evidence` | Statement has no evidence at all |
| `potential_fabrication` | Theorem depends on unverified evidence |
| `diff_divergence` | Two computation paths give different results |

Diffs are the primary mechanism for cross-validation. Register a diff, and the system automatically checks whether swapping one value for another causes dependent terms to change.

### Built-in Operators

**Arithmetic**: `+`, `-`, `*`, `/`, `mod`
**Comparison**: `>`, `<`, `>=`, `<=`, `=`, `!=`
**Logic**: `and`, `or`, `not`, `implies`
**Special forms**: `if`, `let`

```python
s.evaluate([Symbol('+'), 2, 3])          # 5
s.evaluate([Symbol('if'), True, 42, 0])  # 42
```

## Demos

**Apples** ([`parseltongue/core/demos/apples/`](parseltongue/core/demos/apples/)) — Peano arithmetic grounded in observational field notes. Introduces primitive symbols (zero, successor), states axioms with `:evidence`, and derives theorems via `:bind` instantiation.

```bash
python -m parseltongue.core.demos.apples.demo
```

**Revenue Reports** ([`parseltongue/core/demos/revenue_reports/`](parseltongue/core/demos/revenue_reports/)) — Company performance analysis from Q3 reports, targets memos, and bonus policy documents. Shows quote verification, fabrication propagation, diffs, and manual override.

```bash
python -m parseltongue.core.demos.revenue_reports.demo
```

**Biomarkers** ([`parseltongue/core/demos/biomarkers/`](parseltongue/core/demos/biomarkers/)) — Diagnostic marker analysis from competing medical papers. Encodes sensitivity, specificity, and clinical claims, then cross-checks for contradictions between studies.

```bash
python -m parseltongue.core.demos.biomarkers.demo
```

**LLM Revenue** ([`parseltongue/llm/demos/revenue/`](parseltongue/llm/demos/revenue/)) — Same revenue scenario but fully automated via the four-pass LLM pipeline.

```bash
python -m parseltongue.llm.demos.revenue.demo
```

## LLM Pipeline — Deep Dive

This section is for developers who want to understand or extend the pipeline internals.

### Four Passes

Each pass uses LLM tool calling (`tool_choice="required"`) — the model outputs structured DSL, never raw prose.

| Pass | Tool | Input | Output |
|---|---|---|---|
| **1. Extract** | `extract` | Full documents + query | Facts, axioms, terms with `:evidence` |
| **2. Derive** | `derive` | **Blinded** system state (names and types, no values) + query | Derivations and diffs |
| **3. Fact-Check** | `factcheck` | Full system state (all values visible) + query | Alternative computation paths, each ending in a `(diff ...)` |
| **4. Answer** | `answer` | Full system state + query | Grounded markdown with `[[type:name]]` references |

Pass 2 is **blinded** to fact values, forcing the LLM to reason about structure rather than guess numbers. Pass 3 sees everything and cross-validates — every verification angle must end with a diff so the engine can detect divergences mechanically.

### Provider Interface

The pipeline is backend-agnostic. Implement `LLMProvider.complete()` to use any model:

```python
from llm import LLMProvider

class MyProvider(LLMProvider):
    def complete(self, messages: list[dict], tools: list[dict], **kwargs) -> dict:
        # Send messages + tools, force a tool call, return parsed arguments
        # Must return e.g. {"dsl_output": "..."} or {"markdown": "..."}
        ...
```

The default `OpenRouterProvider` supports extended thinking:

```python
provider = OpenRouterProvider(model="anthropic/claude-sonnet-4.6")
provider = OpenRouterProvider(model="anthropic/claude-sonnet-4.6", reasoning=True)     # adaptive
provider = OpenRouterProvider(model="anthropic/claude-sonnet-4.6", reasoning=8000)     # explicit budget
```

### Reference Resolution

Pass 4 markdown contains `[[type:name]]` tags. The resolver maps each to the formal system:

- `[[fact:revenue-q3]]` — evaluates the fact's value
- `[[term:bonus-amount]]` — evaluates the term's definition
- `[[axiom:add-commutative]]` — the axiom's WFF as s-expression
- `[[theorem:target-exceeded]]` — the theorem's WFF + derivation sources
- `[[quote:revenue-q3]]` — full provenance chain back to source document
- `[[diff:growth-check]]` — diff result with divergences (if any)

### Key Files

| File | Purpose |
|---|---|
| `llm/pipeline.py` | Orchestrates the 4 passes |
| `llm/provider.py` | `LLMProvider` ABC + `OpenRouterProvider` |
| `llm/tools.py` | Tool schemas for each pass |
| `llm/prompts.py` | Prompt builders (system + user messages) |
| `llm/dsl_reference.py` | Formats system state for prompts (blinded vs full) |
| `llm/resolve.py` | `[[type:name]]` tag resolution |

## Project Structure

```
parseltongue/
  __init__.py                          # top-level API
  pyproject.toml
  core/
    __init__.py                        # core public API
    atoms.py                           # s-expression reader, types (Symbol, Evidence, ...)
    lang.py                            # DSL grammar, keywords, documentation
    engine.py                          # System runtime, evaluation, consistency
    quote_verifier/                    # quote verification against source documents
      config.py                        #   confidence levels, penalties
      verifier.py                      #   main QuoteVerifier class
      normalizer.py                    #   6-step normalization pipeline
      index.py                         #   inverted index for fast matching
    demos/
      apples/                          # Peano arithmetic demo
      revenue_reports/                 # company performance demo
      biomarkers/                      # diagnostic marker demo
    tests/                             # 290+ unit tests
  llm/
    __init__.py                        # llm public API
    pipeline.py                        # 4-pass pipeline orchestrator
    provider.py                        # LLMProvider interface + OpenRouterProvider
    tools.py                           # tool definitions for each pass
    prompts.py                         # prompt builders for each pass
    dsl_reference.py                   # system state formatters (blinded + full)
    resolve.py                         # [[type:name]] reference resolver
    demos/
      revenue/                         # end-to-end LLM pipeline demo
    tests/                             # 70+ unit tests
```

## Running Tests

```bash
pip install -e ".[dev,llm]"
pytest                           # all tests
pytest core/tests/               # core only
pytest llm/tests/                # llm only
pytest -v -k "QuoteVerifier"     # specific test class
```

## License

Apache 2.0
