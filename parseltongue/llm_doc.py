"""
Parseltongue LLM documentation — assembled reference for AI agents.

Call ``parseltongue.llm_doc()`` to get the full reference as a string.
"""

from typing import Any

from .core import LANG_DOCS, System


def _dsl_reference() -> str:
    """Format the DSL directive/keyword reference from LANG_DOCS."""
    lines: list[str] = []
    categories: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for sym, raw in LANG_DOCS.items():
        d: dict[str, Any] = raw  # type: ignore[assignment]
        categories.setdefault(d["category"], []).append((sym, d))

    titles = {
        "special": "Special Forms",
        "directive": "DSL Directives",
        "structural": "Structural",
        "keyword": "Keyword Arguments",
    }
    for cat in ("special", "directive", "structural", "keyword"):
        entries = categories.get(cat, [])
        if not entries:
            continue
        lines.append(f"\n### {titles[cat]}")
        for sym, d in entries:
            lines.append(f"\n**{sym}**")
            lines.append(d["description"])
            lines.append(f"  Example: {d['example']}")
            if "patterns" in d:
                for pat in d["patterns"][:2]:
                    lines.append(f"  ```\n  {pat}\n  ```")
    return "\n".join(lines)


def _operators_reference() -> str:
    """Format the default operators available when initial_env is not overridden."""
    lines = [
        "\n### Default Operators (available unless initial_env={} is passed)",
        "",
        "Arithmetic: +, -, *, /, %",
        "Comparison: >, <, >=, <=, =, !=",
        "Logic: and, or, not, implies",
        "",
        "These are Python-backed operators. In a purely formal system,",
        "pass initial_env={} to load_main() to start with an empty env.",
    ]
    return "\n".join(lines)


def llm_doc() -> str:
    """Return the full Parseltongue reference for LLM agents.

    Covers:
    - What Parseltongue is
    - Built-in system documentation (all operators, directives, keywords)
    - .pltg file format and directives
    - How to run .pltg files from Python
    - Module/import system
    - Effects and environment extension
    - Complete examples
    """
    system_doc = System().doc()
    return "\n".join(
        [
            _header(),
            _pltg_format(),
            _dsl_reference(),
            _operators_reference(),
            _module_system(),
            _effects_and_env(),
            _running_pltg(),
            _example_minimal(),
            _example_with_modules(),
            _example_entry_mocks(),
            _workflow(),
            _tips(),
            _validation_patterns(),
            "\n## Built-in System Reference\n",
            system_doc,
        ]
    )


def _header() -> str:
    return """# Parseltongue — LLM Reference

Parseltongue is an S-expression DSL for building formal systems with
evidence grounding. Claims are tied to source documents via verifiable
quotes, derivations track provenance, and consistency is checked
automatically.

Two ways to use it:
1. **Write .pltg files** — standalone DSL scripts loaded via Python
2. **Python API** — `System` + `load_source()` for inline usage"""


def _pltg_format() -> str:
    return """
## .pltg File Format

Files use S-expression syntax with semicolon comments:

```scheme
; This is a comment
(directive name body :keyword value ...)
```

### Core Directives

**(fact name value :evidence ...)**
Ground truth. Stored in env, available to expressions.
```scheme
(fact revenue 15 :origin "Q3 report")
(fact sensitivity 94.5
    :evidence (evidence "Paper A"
        :quotes ("Calprotectin sensitivity was 94.5%")
        :explanation "Diagnostic accuracy metric"))
```

**(axiom name wff :evidence ...)**
Parametric rewrite rule. MUST contain at least one ?-variable.
```scheme
(axiom add-identity (= (+ ?n zero) ?n)
    :origin "Peano arithmetic")
```

**(defterm name [body] :evidence ...)**
Named term. Three forms:
- Forward declaration (no body): `(defterm zero :origin "primitive")`
- Computed: `(defterm total (+ a b) :origin "definition")`
- Alias: `(defterm zero src.primitives.zero :origin "import")`

Terms are lazy — body is not evaluated until referenced.

**(derive name axiom-or-wff :bind ... :using ...)**
Derive a theorem. Two modes:
- **Direct**: `(derive d1 (> x 0) :using (x))`
- **Instantiation**: Bind ?-variables in a named axiom:
  ```scheme
  (derive three-plus-zero add-identity
      :bind ((?n (succ (succ (succ zero)))))
      :using (add-identity succ zero))
  ```

**(diff name :replace sym-a :with sym-b)**
Lazy what-if comparison. Shows how dependents diverge when sym-a
is swapped for sym-b.
```scheme
(diff scenario-check :replace original-value :with alternative-value)
```

### Evidence

Prefer `:evidence` with verifiable quotes over plain `:origin`:
```scheme
:evidence (evidence "Document Name"
    :quotes ("exact quote from document")
    :explanation "why this supports the claim")
```
`:origin` is for hypotheticals, imports, and synthesized claims only.
Ungrounded evidence propagates as fabrication taint through derivations."""


def _module_system() -> str:
    return """
## Module / Import System

**(import (quote module.name))**
Import a .pltg file. Path resolved relative to the importing file's directory.
`src.math` → `src/math.pltg`. Definitions in imported modules are automatically
namespaced: `zero` in `src.math` becomes `src.math.zero`.

Use aliases to create local names:
```scheme
(import (quote src.primitives))
(defterm zero src.primitives.zero :origin "import")
```

**(load-document "name" "relative/path.txt")**
Load a source document for quote verification. Path relative to current file.

**(run-on-entry (quote (directive ...)) ...)**
Deferred directives that only execute when the file is the **main entry point**.
Skipped when the file is imported. Useful for self-tests:
```scheme
(run-on-entry
    (quote (fact self-test-passed
        (let ((primitives.zero 0) (primitives.plus +) (primitives.equals =))
            (primitives.equals (primitives.plus 5 primitives.zero) 5))
        :origin "self-test")))
```

**(context :key)**
Returns loader context: `:file`, `:dir`, `:name`, or `:main` (bool)."""


def _effects_and_env() -> str:
    return """
## Effects and Environment Extension

Effects are Python functions callable from .pltg as S-expressions.
The system auto-injects `system` as the first argument.

```python
def my_print(system, *args):
    print(*[str(a) for a in args])
    return True

def my_check(system, name):
    return name in system.facts

load_main("demo.pltg", {
    "print": my_print,
    "check-fact": my_check,
})
```

Then in .pltg:
```scheme
(print "hello from pltg")
(check-fact "revenue")
```

### Built-in Loader Effects (always available in .pltg files)
- `print` — `(print "hello" value ...)` — print to stdout
- `consistency` — `(consistency)` — print the full consistency report
- `import` — load another .pltg module
- `run-on-entry` — deferred execution (main only)
- `load-document` — register source document
- `context` — query loader context

### System kwargs
Passed through to System() constructor:
- `initial_env={}` — start with empty env (no default operators)
- `overridable=True` — allow redefining facts/terms"""


def _running_pltg() -> str:
    return """
## Running .pltg Files

### From the command line

```bash
python -m parseltongue load_main path/to/demo.pltg
```

### Minimal Python launcher

```python
import os
from parseltongue import load_main

os.chdir(os.path.dirname(__file__))
system = load_main("my_program.pltg", {
    "print": lambda _sys, *args: print(*args) or True,
})
```

### With logging and custom effects

```python
import logging
import os
import sys
from parseltongue import load_main

def pltg_print(_system, *args):
    print(*[str(a).replace("\\\\n", "\\n") for a in args])
    return True

def print_facts(system):
    for name, fact in system.facts.items():
        print(f"  {name} = {fact.wff}")
    return True

if __name__ == "__main__":
    plog = logging.getLogger("parseltongue")
    plog.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("  [%(levelname)s] %(message)s"))
    plog.addHandler(handler)

    os.chdir(os.path.dirname(__file__))
    load_main("demo.pltg", {
        "print": pltg_print,
        "print-facts": print_facts,
    })
```

### Purely formal system (no Python operators)

```python
load_main("demo.pltg", effects, initial_env={}, overridable=True)
```

This removes default +, >, = etc. from env. All symbols are formal
until explicitly mocked via let or provided as effects."""


def _example_minimal() -> str:
    return """
## Example: Minimal Single-File

```scheme
; analysis.pltg
(load-document "Report" "data/q3_report.txt")

(fact revenue 15
    :evidence (evidence "Report"
        :quotes ("Q3 revenue was $15M")
        :explanation "Revenue figure"))

(fact target 12
    :evidence (evidence "Report"
        :quotes ("Growth target was $12M")
        :explanation "Target figure"))

(derive target-exceeded (> revenue target)
    :using (revenue target))
```

```python
# run.py
import os
from parseltongue import load_main
os.chdir(os.path.dirname(__file__))
system = load_main("analysis.pltg")
print(system.evaluate(system.theorems["target-exceeded"].wff))  # True
```"""


def _example_with_modules() -> str:
    return """
## Example: Multi-Module with Imports

Directory layout:
```
project/
  demo.py
  demo.pltg
  resources/
    observations.txt
  src/
    primitives.pltg
    axioms.pltg
    morning.pltg
```

**src/primitives.pltg** — forward-declared symbols:
```scheme
(defterm zero
    :evidence (evidence "Observations"
        :quotes ("An empty basket is zero")
        :explanation "Zero: empty collection"))
(defterm succ :origin "primitive")
(defterm = :origin "primitive")
(defterm + :origin "primitive")
```

**src/axioms.pltg** — imports primitives, defines axioms:
```scheme
(defterm zero src.primitives.zero :origin "import")
(defterm succ src.primitives.succ :origin "import")
(defterm = src.primitives.= :origin "import")
(defterm + src.primitives.+ :origin "import")

(axiom add-identity (= (+ ?n zero) ?n) :origin "Peano")
(axiom add-commutative (= (+ ?a ?b) (+ ?b ?a)) :origin "Peano")
```

**demo.pltg** — main orchestration:
```scheme
(load-document "Observations" "resources/observations.txt")
(import (quote src.primitives))
(import (quote src.axioms))

; Local aliases for convenience
(defterm local-zero src.primitives.zero :origin "import")
(defterm local-succ src.primitives.succ :origin "import")

; Derive concrete theorem
(derive three-plus-zero src.axioms.add-identity
    :bind ((?n (local-succ (local-succ (local-succ local-zero)))))
    :using (src.axioms.add-identity local-succ local-zero))
```

**demo.py**:
```python
import os
from parseltongue import load_main

os.chdir(os.path.dirname(__file__))
system = load_main("demo.pltg", {
    "print": lambda _s, *a: print(*a) or True,
}, initial_env={}, overridable=True)
```"""


def _example_entry_mocks() -> str:
    return """
## Example: run-on-entry Self-Tests with let Mocks

A module can include its own unit tests via run-on-entry.
Forward-declared primitives (no body) are rebound by let
to concrete values, making formal theorems computable.

**src/math.pltg**:
```scheme
(import (quote primitives))
(import (quote axioms))

(defterm zero primitives.zero :origin "import")
(defterm succ primitives.succ :origin "import")
(defterm equals primitives.equals :origin "import")
(defterm plus primitives.plus :origin "import")

; Formal theorem — all symbols are unresolved
(derive three-plus-zero axioms.add-identity
    :bind ((?n (succ (succ (succ zero)))))
    :using (axioms.add-identity succ zero))

; Self-test: only fires when math.pltg is the entry point.
; let rebinds the forward-declared primitives to concrete mocks.
(run-on-entry
    (quote (assert-true "add-identity: 5 + 0 = 5"
        (let ((primitives.zero 0)
              (primitives.plus +)
              (primitives.equals =))
            (primitives.equals (primitives.plus 5 primitives.zero) 5))))
    (quote (assert-true "three-plus-zero theorem"
        (let ((primitives.zero 0)
              (primitives.succ mock-succ)
              (primitives.plus +)
              (primitives.equals =))
            three-plus-zero))))
```

When imported by another file, the run-on-entry block is skipped.
When run directly, it executes and the let bindings make the formal
expressions compute to True."""


def _workflow() -> str:
    return """
## Workflow: Standard Verification Sequence

### Step 0: Decide Source Tuples

Identify which sources must be mutually consistent. A "source tuple"
is a group of documents/artifacts that should agree with each other.

Examples:
- **Feature verification**: `(feature_docstrings, feature_readme, feature_code)`
- **Literature review**: `(paper_A_methods, paper_B_methods, meta_analysis)`
- **API audit**: `(openapi_spec, handler_code, integration_tests)`

### Step 1: Build Leaf Modules (one per source)

For each source in the tuple, create a module that:

1. **Load the document** and extract facts with evidence (:quotes)
2. **Define terms** for computed/derived values
3. **Internal consistency check** — within a single source, verify
   that its own claims don't contradict each other

**Minimum for an internal check:**
- At least 2 theorems (derives) or terms that express the same
  concept from different angles
- At least 1 diff that exposes whether those angles agree

You can also diff on "lower-value" facts or terms to surface
contradictions that propagate upward into theorems. Structure:
one top-level diff per check, plus optional supporting diffs below.

```scheme
; src/feature_code.pltg — leaf module for source code
(load-document "auth_module" "resources/auth_module.py.txt")

(fact uses-bcrypt true
    :evidence (evidence "auth_module"
        :quotes ("password = bcrypt.hashpw(password, salt)")
        :explanation "Code uses bcrypt for hashing"))

(fact session-timeout 3600
    :evidence (evidence "auth_module"
        :quotes ("SESSION_TIMEOUT = 3600")
        :explanation "Timeout constant in seconds"))

; Internal check: timeout is within sane range
(derive timeout-minutes (/ session-timeout 60) :using (session-timeout))
(derive timeout-reasonable (and (> timeout-minutes 5) (< timeout-minutes 120))
    :using (timeout-minutes))

; Diff: what if timeout were the common default?
(defterm common-default-timeout 1800 :origin "industry standard")
(diff timeout-vs-default :replace session-timeout :with common-default-timeout)
```

```scheme
; src/feature_readme.pltg — leaf module for README
(load-document "README" "resources/readme.txt")

(fact readme-hashing "argon2"
    :evidence (evidence "README"
        :quotes ("Uses Argon2 for password hashing")
        :explanation "README claims Argon2"))

(fact readme-timeout 1800
    :evidence (evidence "README"
        :quotes ("Sessions expire after 30 minutes")
        :explanation "README claims 30min timeout"))

; Internal check: README claims are self-consistent
(derive readme-timeout-minutes (/ readme-timeout 60) :using (readme-timeout))
(derive readme-timeout-matches-prose (= readme-timeout-minutes 30)
    :using (readme-timeout-minutes))
```

### Step 2: Cross-Check Module (one per source tuple)

Import all leaf modules. Create **local aliases** for namespaced
symbols to keep expressions readable — `defterm` with another term
as body acts as a lazy alias:

```scheme
; feature_main.pltg — cross-check module
(import (quote src.feature_code))
(import (quote src.feature_readme))

; Aliases — short local names for imported symbols
(defterm code-hashing src.feature_code.uses-bcrypt :origin "import")
(defterm code-timeout src.feature_code.session-timeout :origin "import")
(defterm readme-hashing src.feature_readme.readme-hashing :origin "import")
(defterm readme-timeout src.feature_readme.readme-timeout :origin "import")
```

Work **only at the level of theorems and diffs** — do not re-extract
facts. Apply the same rules: at least 2 theorems/terms + at least
1 diff per cross-check.

```scheme
; Cross-check: do code and README agree on timeout?
(derive code-timeout-minutes (/ code-timeout 60) :using (code-timeout))
(derive readme-timeout-minutes (/ readme-timeout 60) :using (readme-timeout))

; Top-level diff: swap code's timeout for README's claim
(diff timeout-mismatch
    :replace code-timeout
    :with readme-timeout)

; Cross-check: hashing algorithm
; README says argon2, code says bcrypt — diff exposes the contradiction
(diff hashing-mismatch
    :replace code-hashing
    :with readme-hashing)

(consistency)
```

Aliases are lazy — `(defterm code-timeout src.feature_code.session-timeout)`
stores the reference, not the value. The alias resolves at evaluation
time, so diffs that replace the underlying symbol propagate correctly
through the alias chain.

### Step 3: Compose Higher-Level Abstractions

Cross-check modules are themselves composable. Once you have verified
modules for individual units, import them into a higher-level module
for system-wide verification. Same rules apply at every level.

```
project/
  run.py
  system_verify.pltg          ← imports feature mains
  features/
    auth/
      auth_main.pltg           ← cross-check for auth
      src/
        auth_code.pltg         ← leaf: auth source code
        auth_readme.pltg       ← leaf: auth docs
    billing/
      billing_main.pltg        ← cross-check for billing
      src/
        billing_code.pltg
        billing_spec.pltg
```

At each level:
- Import child modules
- Create aliases for their exported theorems/terms
- Work with theorems and diffs (not raw facts)
- Create cross-cutting diffs to expose inter-module contradictions

### Summary: The Verification Pyramid

```
            ┌─────────────────┐
            │  system_verify  │  system-wide cross-checks
            └────────┬────────┘
         ┌───────────┴───────────┐
    ┌────┴─────┐           ┌────┴─────┐
    │auth_main │           │bill_main │  per-unit cross-checks
    └────┬─────┘           └────┬─────┘
    ┌────┴────┐           ┌────┴────┐
  ┌─┴──┐  ┌──┴─┐       ┌─┴──┐  ┌──┴─┐
  │code│  │docs│       │code│  │spec│   leaf modules (1 per source)
  └────┘  └────┘       └────┘  └────┘
```

Each leaf: facts + terms + internal diffs.
Each cross-check: aliases + theorems + diffs across children.
Each higher level: same pattern, composing cross-checks.

This works for code verification, literature review, compliance
auditing, multi-source journalism, and any domain where claims
from multiple sources must be reconciled."""


def _tips() -> str:
    return """
## Tips for LLMs

1. **Always ground claims** — use :evidence with :quotes from loaded documents.
   :origin is for imports, hypotheticals, and synthesized conclusions only.
   Grounding MUST make the quote unique for the doc.

2. **Axioms need ?-variables** — `(axiom name (= ?x ?x))` not `(axiom name (= 1 1))`.
   Ground claims use `(fact ...)` or `(derive ...)`.

3. **Derive has two modes** — don't mix them:
   - Direct: `(derive name (expression) :using (sources))`
   - Instantiation: `(derive name axiom-name :bind ((?var val)) :using (axiom-name ...))`

4. **Module namespacing** — imported definitions are prefixed with module name.
   Use `(defterm local-name module.name :origin "import")` for aliases.

5. **Terms are lazy** — `(defterm x (+ a b))` stores the expression, not the result.
   Evaluation happens when referenced.

6. **Consistency matters** — run `system.consistency()` to check for ungrounded
   evidence, fabrication taint, and diff divergences.

7. **initial_env={}** — use this for purely formal/symbolic systems where you
   don't want Python operators (+, >, = etc.) in the environment.

8. **Inspecting the system** after loading:
   ```python
   system.facts          # dict of facts
   system.terms          # dict of terms
   system.axioms         # dict of axioms
   system.theorems       # dict of theorems
   system.documents      # dict of loaded documents
   system.consistency()  # consistency report
   system.provenance(name)  # derivation chain
   system.evaluate(expr)    # evaluate expression
   ```"""


def _validation_patterns() -> str:
    return """
## Validation Patterns: Counting, Pairing, and Proving

When building self-validating .pltg modules that prove code is correct,
follow these patterns. The goal: every fact is reachable from a diff,
every claim is grounded in source quotes, and cross-checks surface
real bugs.

### Pattern 1: Items × Layers (count-exists)

When a codebase has N items that each appear in multiple representations
(declaration, documentation, implementation), create a fact per item
per layer, then count and diff.

**Example**: 15 operators × 3 layers (declaration, docs, implementation).

```scheme
; Layer 1: DECL — Symbol constants
(fact add-decl true
    :evidence (evidence "source.py"
        :quotes ("ADD = Symbol(\\\"+ \\\")")
        :explanation "ADD symbol declared"))

; Layer 2: DOCS — documentation entries
(fact add-docs true
    :evidence (evidence "source.py"
        :quotes ("Add two numbers.")
        :explanation "ADD has docs entry"))

; Layer 3: IMPL — runtime mapping
(fact add-impl true
    :evidence (evidence "source.py"
        :quotes ("ADD: operator.add,")
        :explanation "ADD maps to operator.add"))

; ... repeat for all items ...

; Per-layer counts
(derive decl-count (count-exists add-decl sub-decl mul-decl ...)
    :using (count-exists add-decl sub-decl mul-decl ...))
(derive docs-count (count-exists add-docs sub-docs mul-docs ...)
    :using (count-exists add-docs sub-docs mul-docs ...))
(derive impl-count (count-exists add-impl sub-impl mul-impl ...)
    :using (count-exists add-impl sub-impl mul-impl ...))

; Cross-layer diffs — layers must agree
(diff decl-vs-docs :replace decl-count :with docs-count)
(diff docs-vs-impl :replace docs-count :with impl-count)
```

**Key rule**: Never hardcode counts as `(defterm X-count 5 :evidence ...)`.
Always derive counts from facts using `count-exists`. The count must
emerge from the evidence, not be asserted.

### Pattern 2: Paired Boolean Count (and)

When you need to prove that EVERY item has ALL layers confirmed,
use the paired `(and ...)` inside `count-exists`:

```scheme
(derive all-layers-paired-count
    (count-exists (and add-decl add-docs add-impl)
                  (and sub-decl sub-docs sub-impl)
                  (and mul-decl mul-docs mul-impl)
                  ...)
    :using (count-exists
            add-decl add-docs add-impl
            sub-decl sub-docs sub-impl
            mul-decl mul-docs mul-impl ...))

; Paired count must match each individual layer total
(diff paired-vs-decl :replace all-layers-paired-count :with decl-count)
(diff paired-vs-docs :replace all-layers-paired-count :with docs-count)
(diff paired-vs-impl :replace all-layers-paired-count :with impl-count)
```

If any item is missing a layer, the paired count drops below the
layer count and the diff fires. This catches partial coverage.

### Pattern 3: Extracting Axioms from Code

Source code contains implicit invariants. Extract them as axioms
with ?-variables, then prove each instance with derives.

**What to look for**:
- Ordering invariants (penalty chains, priority levels)
- Conditional rules (if X then Y patterns)
- Safety invariants (never empty, always positive, fallback behavior)
- Computation rules (score = 1.0 - penalties, dilution formulas)

```scheme
; Axiom: penalties are ordered by semantic impact
(axiom penalty-ordering (> ?heavy ?light)
    :evidence (evidence "config.py"
        :quotes ("dangerous: 0.31" "stopword: 0.125" "case: 0.01")
        :explanation "Penalties ordered by impact"))

; Axiom: empty input is rejected
(axiom empty-rejected (implies (not ?has-content) (= ?verified false))
    :evidence (evidence "verifier.py"
        :quotes ("if not quote.strip():
            return {
                ...
                \\\"verified\\\": False,
                \\\"reason\\\": \\\"Empty quote\\\",
            }, False")
        :explanation "Empty quotes return not-verified"))

; Axiom: safety net keeps at least one word
(axiom keep-one (implies ?all-stopwords (= ?kept 1))
    :evidence (evidence "normalizer.py"
        :quotes ("all_stopwords = all(w.lower() in config.stopwords for w in words)
    if all_stopwords:
        words_to_keep = [words[0]]")
        :explanation "First word kept when all are stopwords"))
```

**Quoting rule**: Quote the contiguous code segment that PROVES the
claim. Not the minimum substring, not a comment — the actual code
path that demonstrates the behavior. Include the condition AND the
consequence.

### Pattern 4: Connecting Axioms to Derives

Axioms are patterns, not values. They cannot appear in `(and ...)`
expressions. Connect them via `:using` in derives:

```scheme
; Each derive proves one instance of the axiom
(derive whitespace-lt-case
    (< penalty-whitespace penalty-case)
    :using (penalty-ordering penalty-whitespace penalty-case))

; The axiom appears in :using — it's a dependency, not an operand
```

For axioms about code behavior (not rewrite rules), create impl
facts that quote the actual code, then count the impl facts with
the axioms as `:using` dependencies:

```scheme
(fact empty-rejected-impl true
    :evidence (evidence "verifier.py"
        :quotes ("if not quote.strip(): ... \\\"verified\\\": False")
        :explanation "Empty quotes rejected in pre_validate"))

(derive axiom-impl-count
    (count-exists empty-rejected-impl keep-one-impl score-init-impl ...)
    :using (count-exists
            empty-rejected keep-one score-starts-at-one  ; axioms as deps
            empty-rejected-impl keep-one-impl score-init-impl ...))
```

### Pattern 5: Category Counts vs Individual Counts

When items belong to categories, verify both directions:

```scheme
; Category membership fact
(fact arithmetic-op-count 5
    :evidence (evidence "source.py"
        :quotes ("ARITHMETIC_OPS = (ADD, SUB, MUL, DIV, MOD)")
        :explanation "5 arithmetic operators"))

; Individual item count per category
(derive arith-decl-count
    (count-exists add-decl sub-decl mul-decl div-decl mod-decl)
    :using (count-exists add-decl sub-decl mul-decl div-decl mod-decl))

; Category count must match individual count
(diff arith-decl-vs-category :replace arith-decl-count :with arithmetic-op-count)
```

### Pattern 6: Multi-Stage Proof Ending in Diffs

A complete validation module follows this structure:

1. **Facts** — one per claim, grounded in source quotes
2. **Axioms** — invariants extracted from code patterns
3. **Per-group count-exists derives** — count facts per layer/category
4. **Ordering/relationship derives** — prove invariants hold
5. **Paired boolean count** — prove all items have all layers
6. **Diffs** — compare counts that should match

Every fact must be reachable from at least one diff (no dangling).
Every axiom must appear in at least one derive's `:using`.
Every derive must feed into a diff or another derive that does.

**Ordering constraint**: Diffs can only reference definitions that
appear BEFORE them in the file. The loader namespaces symbols as
they're registered, so a diff referencing a not-yet-defined derive
will fail to resolve.

### Anti-Patterns

- **Hardcoded counts**: `(defterm count 5 :evidence ...)` — always
  derive counts from facts via count-exists
- **Quoting comments as impl**: `"# This does X"` is not implementation.
  Quote the actual code that does X.
- **Minimum quotes**: Don't reduce quotes to the smallest substring.
  Quote enough to prove the claim — the condition AND the consequence.
- **Tautological diffs**: Don't diff things that can't meaningfully
  diverge. `count-exists(a, b, c) = 3` vs `(+ 1 2) = 3` proves nothing.
- **Dangling definitions**: If a fact isn't reachable from any diff,
  it's dead weight. Either connect it or remove it.
  Exception: specification modules (see Pattern 7).

### Pattern 7: Specification / README Modules

A specification module (README, API spec, design doc) exports
**expectations** — claims about what the codebase should do. These
expectations are consumed by a cross-check module that diffs them
against implementation facts.

**Key principle**: A specification module can only prove its OWN
internal consistency. It cannot prove the codebase is correct — that
happens in the cross-check module. Most of its facts will be
correctly dangling.

#### What a spec module contains

1. **Facts** — one per claim the spec makes, grounded in spec quotes
2. **Axioms** — universal rules the spec states ("every fact must
   cite a quote", "axioms require ?-variables")
3. **Internal diffs** — ONLY where the spec states a numeric count
   AND separately lists the individual items

#### The stated-count pattern (the only valid internal diff)

A README says "five directive types" (a count fact) and then lists
fact, axiom, defterm, derive, diff (individual listing facts). The
stated count and the listing are two independent claims in the same
document. Diff them:

```scheme
; Stated count from prose
(fact directive-count 5
    :evidence (evidence "README"
        :quotes ("five directive types")
        :explanation "README states the count"))

; Individual listings
(fact has-fact-directive true
    :evidence (evidence "README"
        :quotes ("**fact** — ground truth")
        :explanation "README lists fact directive"))
; ... 4 more listing facts ...

; Count the listings
(derive directive-listing-count
    (count-exists has-fact-directive has-axiom-directive
                  has-defterm-directive has-derive-directive has-diff-directive)
    :using (count-exists has-fact-directive has-axiom-directive
                         has-defterm-directive has-derive-directive has-diff-directive))

; Diff stated count vs actual listing — catches "says 5 but lists 4"
(diff directive-listing-vs-stated
    :replace directive-listing-count :with directive-count)
```

#### Paired coverage across layers within the spec

When the spec has two independent layers per item (e.g., a listing
AND a description), use paired boolean count:

```scheme
; Each directive has a listing AND a description
(derive directive-paired-count
    (count-exists (and has-fact-directive fact-description)
                  (and has-axiom-directive axiom-description)
                  (and has-defterm-directive defterm-description)
                  (and has-derive-directive derive-description)
                  (and has-diff-directive diff-description))
    :using (count-exists
            has-fact-directive fact-description
            has-axiom-directive axiom-description
            has-defterm-directive defterm-description
            has-derive-directive derive-description
            has-diff-directive diff-description))

; Paired must match listing count
(diff directive-paired-vs-listing
    :replace directive-paired-count :with directive-listing-count)
```

#### What is NOT a valid internal diff

- **Counting your own inventory**: If you wrote 7 facts about
  rationale claims, `(count-exists claim1 claim2 ... claim7) = 7`
  vs `(count-exists claim1 claim2 ... claim7) = 7` is tautological.
  Both sides count the same facts you just wrote. There is no
  independent source to disagree.

- **Axiom-backing counts**: In a spec module, every axiom already
  has a backing fact because every claim cites a quote from the
  spec document. Checking "does this axiom have evidence?" is
  tautological — you wrote both.

- **Section inventories**: Counting how many facts you extracted
  from a section and diffing against... the same count. You are
  the only source of both numbers.

#### Valid internal diffs require TWO INDEPENDENT claims

The spec must make the same claim in two different ways:
1. A prose count ("ships with 11 demos") — one fact
2. An enumerated list (11 individual demo entries) — N facts

These are independent because the author could write "11" in prose
but list 10 items. The diff catches that.

#### Dangling exports are correct

Most spec facts will be dangling in the spec module. They are
consumed by the cross-check module:

```scheme
; In cross_check.pltg:
(import (quote readme))
(import (quote code))

; Diff README's expectation against code's reality
(diff timeout-mismatch
    :replace readme.readme-timeout
    :with code.actual-timeout)
```

The spec module's job is to faithfully extract what the spec says.
The cross-check module's job is to verify the code matches."""
