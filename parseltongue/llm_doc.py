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
            _llm_pipeline(),
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
## Workflow: How to Structure a Parseltongue Project

### Single Document Analysis

For a single document, create one self-contained module:

1. **Load the document** and extract all facts with evidence
2. **Define terms** for computed values referencing those facts
3. **Derive theorems** to prove relationships
4. **Add diffs** for what-if analysis and consistency checks
5. **Run consistency** to verify everything is grounded

```
project/
  run.py
  analysis.pltg
  resources/
    report.txt
```

### Multi-Document / Multi-Source Analysis

Process documents bottom-up. Each source gets its own module,
then a top-level file cross-checks across sources.

**Step 1: Process each document independently.**
Create a module per source with its own facts, terms, and internal
consistency checks.

```
project/
  run.py
  verify.pltg              ← top-level cross-check
  src/
    code_module.pltg        ← facts from source code
    readme.pltg             ← facts from README
    spec.pltg               ← facts from spec document
```

**Step 2: Start with the most concrete sources.**
Code files and raw data first — these are ground truth.
Then documentation, READMEs, specs — these make claims about
the concrete sources.

```scheme
; src/code_module.pltg — extract from source code
(defterm auth-uses-bcrypt true
    :evidence (evidence "auth_module"
        :quotes ("password = bcrypt.hashpw(password, salt)")
        :explanation "Code uses bcrypt for password hashing"))

(defterm session-timeout 3600
    :evidence (evidence "auth_module"
        :quotes ("SESSION_TIMEOUT = 3600")
        :explanation "Session timeout constant in seconds"))
```

```scheme
; src/readme.pltg — extract from documentation
(defterm readme-claims-argon2 true
    :evidence (evidence "README"
        :quotes ("Uses Argon2 for password hashing")
        :explanation "README claims Argon2 is used"))

(defterm readme-claims-timeout 1800
    :evidence (evidence "README"
        :quotes ("Sessions expire after 30 minutes")
        :explanation "README claims 30-minute timeout"))
```

**Step 3: Cross-check in the top-level file.**
Import all modules, then diff claims against ground truth.

```scheme
; verify.pltg — cross-source validation
(load-document "auth_module" "resources/auth_module.py.txt")
(load-document "README" "resources/readme.txt")

(import (quote src.code_module))
(import (quote src.readme))

; Diff: does the README match the code?
(diff hashing-check
    :replace src.code_module.auth-uses-bcrypt
    :with src.readme.readme-claims-argon2)

(diff timeout-check
    :replace src.code_module.session-timeout
    :with src.readme.readme-claims-timeout)

(consistency)
```

This pattern scales: add more source modules, each self-contained
with their own facts and evidence, then cross-check at the top level.

### Key Principle: Bottom-Up, Then Cross-Check

1. **Leaf modules** — one per source document, self-contained facts
2. **Intermediate modules** — combine related sources, derive terms
3. **Top-level** — imports everything, runs diffs across sources
4. **run-on-entry** — each module can self-test when run standalone"""


def _llm_pipeline() -> str:
    return """
## LLM-Powered Pipeline (Automated Analysis)

Parseltongue includes a four-pass LLM pipeline that automates the
entire workflow — extraction, derivation, fact-checking, and reporting.

```python
from parseltongue.core import System
from parseltongue.llm import Pipeline
from parseltongue.llm.openrouter import OpenRouterProvider

system = System(overridable=True)
provider = OpenRouterProvider()

pipeline = Pipeline(system, provider)
pipeline.add_document("Report", path="resources/report.txt")

result = pipeline.run("Did we beat our growth target?")
print(result.output)
```

### The Four Passes

1. **Extraction** — LLM reads source documents, outputs facts/terms/axioms
   as Parseltongue directives with :evidence from verbatim quotes
2. **Derivation** — LLM sees fact names/types (NOT values), builds
   logical derivations and diffs from structural relationships
3. **Fact Check** — LLM sees full evaluated state, cross-validates
   by introducing alternative computation paths and diffing
4. **Inference** — LLM writes a human-readable report with inline
   [[type:name]] references linking every claim to evidence

### Multi-Document Pipeline

```python
pipeline.add_document("Code", path="resources/auth_module.py.txt")
pipeline.add_document("README", path="resources/readme.txt")

result = pipeline.run(
    "Validate this README against the actual code. "
    "Are there contradictions?"
)
```

The pipeline handles source ordering internally — the LLM extracts
from all documents in pass 1, then cross-checks in passes 2-3.

### Install LLM dependencies

```bash
pip install parseltongue-dsl[llm]
```"""


def _tips() -> str:
    return """
## Tips for LLMs

1. **Always ground claims** — use :evidence with :quotes from loaded documents.
   :origin is for imports, hypotheticals, and synthesized conclusions only.

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
