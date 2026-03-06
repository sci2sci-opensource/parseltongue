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
