"""
Parseltongue DSL — Language Core.

Language grammar symbols, keyword constants, documentation registry,
and evidence parsing.  Imports and re-exports everything from atoms
for backward compatibility.

Statement-Building Quick Reference
-----------------------------------

Every Parseltongue statement is an s-expression directive:

    (directive name body? :keyword value ...)

Directives:

  fact     — Ground truth value with evidence.
  axiom    — Parametric rewrite rule (must contain ?-variables).
  defterm  — Named term/concept (may be a forward declaration, computed
             expression, or conditional).
  derive   — Theorem derived from existing axioms/facts/terms. Use :bind
             to instantiate parameterised templates.
  diff     — Lazy comparison: what changes if one symbol is swapped for another.
  evidence — Structured evidence block with verifiable :quotes and :explanation.

Evidence can be attached to fact, axiom, and defterm via :origin (plain
string) or :evidence (structured block with verifiable :quotes and
:explanation).

Derives inherit grounding from their sources — a theorem is proven by
its axioms, facts, and computable terms. Diffs require no evidence because inconsistency
between their sides is itself a system-level issue.

See LANG_DOCS below for full syntax and examples drawn from real demos.
"""

from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from .atoms import (  # noqa: F401 — re-export
    SILENCE,
    WFF,
    Axiom,
    Evidence,
    Primitive,
    Silence,
    Symbol,
    Term,
    Theorem,
)
from .grammar import (  # noqa: F401 — deprecated re-export
    Grammar,
    ParseltongueGrammar,
    _pg,
    atom,
    read_tokens,
    to_sexp,
    tokenize,
)
from .morphism import StringMorphism, _pm

# ============================================================
# Clause & Sentence Types
# ============================================================

Clause = WFF | Evidence | Axiom | Theorem | Term
Sentence = Clause | list["Sentence"]


# ============================================================
# Interfaces — Translator, Rewriter, Listener, Interpreter
# ============================================================


_T_co = TypeVar("_T_co", covariant=True)
_T_contra = TypeVar("_T_contra", contravariant=True)


class Translator(Protocol[_T_co]):
    """str → T. Allows the caller to obtain structured meaning from raw text."""

    def translate(self, source: str) -> _T_co: ...


class Rewriter(Protocol):
    """Sentence → Sentence. Allows the caller to reduce or transform expressions."""

    def evaluate(self, expr: Sentence, local_env: dict | None = None) -> Sentence: ...


class Executor(Protocol[_T_contra]):
    """T → Silence. Executes a parsed directive for its side effects."""

    def execute(self, directive: _T_contra) -> Silence: ...


class Listener(Protocol):
    """str → (Listener, Silence). Allows the caller
    to speak and receive an updated listener to continue the conversation."""

    def listen(self, source: str) -> tuple["Listener", Silence]: ...


class Interpreter(Listener, Protocol):
    """str → (Interpreter, Sentence).
    Allows the caller to speak and receive both a response
    and an updated interpreter to continue the conversation."""

    def interpret(self, source: str) -> tuple["Interpreter", Sentence]: ...

    def listen(self, source: str) -> tuple["Interpreter", Silence]:
        new_self, _ = self.interpret(source)
        return (new_self, SILENCE)


# ============================================================
# Language-Level Symbol Constants
# ============================================================

# Special forms — evaluated directly by the interpreter, not via env
# scope receives its args unevaluated and delegates to a registered System
# self evaluates its args in the current engine (identity scope)
# project evaluates in a named basis (default: self) and yields the value
IF = Symbol("if")
LET = Symbol("let")
EQ = Symbol("=")
QUOTE = Symbol("quote")
STRICT = Symbol("strict")
SCOPE = Symbol("scope")
SELF = Symbol("self")
PROJECT = Symbol("project")
DELEGATE = Symbol("delegate")

# DSL keywords — structural symbols of the language
AXIOM = Symbol("axiom")
DEFTERM = Symbol("defterm")
FACT = Symbol("fact")
DERIVE = Symbol("derive")
DIFF = Symbol("diff")
EVIDENCE = Symbol("evidence")

SPECIAL_FORMS = (IF, LET, QUOTE, STRICT, SCOPE, SELF, PROJECT, DELEGATE)
DSL_KEYWORDS = (AXIOM, DEFTERM, FACT, DERIVE, DIFF, EVIDENCE)

# Pattern variable prefixes — used in axiom ?-variables and splat patterns
VAR_PREFIX = "?"
SPLAT_PREFIX = "?..."

# Keyword arguments (plain strings, not Symbols — returned by atom() as-is)
KW_QUOTES = ":quotes"
KW_EXPLANATION = ":explanation"
KW_ORIGIN = ":origin"
KW_EVIDENCE = ":evidence"
KW_USING = ":using"
KW_REPLACE = ":replace"
KW_WITH = ":with"
KW_BIND = ":bind"


# ============================================================
# Language Documentation
# ============================================================

LANG_DOCS = {
    # ----------------------------------------------------------
    # Special forms
    # ----------------------------------------------------------
    IF: {
        "category": "special",
        "description": "Conditional evaluation.  Evaluates the then-branch "
        "if condition is true, the else-branch otherwise.  "
        "Only the taken branch is evaluated (lazy).",
        "example": '(if (> x 0) "positive" "non-positive")',
        "expected": '"positive" (when x > 0)',
        "patterns": [
            # Conditional term from biomarkers demo
            "(defterm clinical-utility\n"
            "    (if (and reliable-marker standalone-diagnostic)\n"
            '        "use-alone"\n'
            '        "use-with-confirmation")\n'
            '    :origin "Synthesized from both papers")',
            # Conditional bonus from revenue demo
            "(defterm bonus-amount\n"
            "    (if (> revenue-q3-growth growth-target)\n"
            "        (* base-salary bonus-rate)\n"
            "        0)\n"
            '    :evidence (evidence "Bonus Policy Doc"\n'
            '      :quotes ("Bonus is 20% of base salary if growth target is exceeded")\n'
            '      :explanation "Bonus calculation formula"))',
        ],
    },
    LET: {
        "category": "special",
        "description": "Local bindings.  Binds names to values in a local scope, then evaluates the body.",
        "example": "(let ((x 10)) (+ x 5))",
        "expected": 15,
    },
    QUOTE: {
        "category": "special",
        "description": "Prevent evaluation.  Returns the expression exactly as "
        "written, without evaluating it.  Useful for passing "
        "raw symbols or expression trees to effects.",
        "example": "(quote (+ 1 2))",
        "expected": "(+ 1 2)  (unevaluated list)",
        "patterns": [
            "(quote some.module.name)",
            "(quote (fact x 10 :origin \"test\"))",
        ],
    },
    STRICT: {
        "category": "special",
        "description": "Force eager evaluation. Within a single system, "
        "(strict x) evaluates x immediately so its structure is visible "
        "to rewrite patterns. Across scope boundaries, strict propagates "
        "via scope: when scope is evaluated inside a strict context, "
        "scope wraps the outer expression it forwards in (strict ...), "
        "notifying the target system that eager evaluation is requested. "
        "The target system processes strict with its own engine — "
        "no definitions change, no ownership is violated.",
        "example": "(joint-status (strict r))",
        "expected": "r is evaluated before joint-status rewrites",
        "patterns": [
            ";; Force eval in lazy context (original use case)\n" "(joint-status (strict r))",
            ";; Strict outside scope: scope wraps the forwarded expr in strict\n" "(strict (scope sieve (+ 1 2)))",
            ";; Propagation chains: each scope boundary wraps once\n"
            "(strict (scope sieve (scope fermat (pow-mod 2 6 7))))",
            ";; Case 1: strict propagates through scopes but not into branches\n"
            ";; rewritten as: (strict (scope outer (strict (scope inner (strict (if cond lazy1 lazy2))))))\n"
            ";; → cond forced, branches stay lazy\n"
            "(strict (scope outer (scope inner (if cond lazy1 lazy2))))",
            ";; Case 2: strict only on branch, no outer propagation\n"
            ";; rewritten as: (scope outer (scope inner (if true (strict lazy1) lazy2)))\n"
            ";; → lazy1 evaluated, lazy2 never reached\n"
            "(scope outer (scope inner (if true (strict lazy1) lazy2)))",
            ";; Case 3: strict on dead branch\n"
            ";; rewritten as: (scope outer (scope inner (if false (strict lazy1) lazy2)))\n"
            ";; → lazy2 evaluated normally, (strict lazy1) never touched\n"
            "(scope outer (scope inner (if false (strict lazy1) lazy2)))",
            ";; Case 4: outer strict does not infect the chosen branch\n"
            ";; rewritten as: (strict (scope outer (strict (scope inner (strict (if false (strict lazy1) lazy2))))))\n"
            ";; → lazy2 evaluated normally despite outer strict\n"
            "(strict (scope outer (scope inner (if false (strict lazy1) lazy2))))",
        ],
    },
    PROJECT: {
        "category": "special",
        "description": "Evaluate an expression in a named basis and yield the value. "
        "With one argument, projects in the current engine (self). "
        "With two arguments, the first names the basis (a scope) and "
        "the second is the expression to evaluate in that basis. "
        "The result is a concrete value — it crosses scope boundaries "
        "without carrying unresolved symbols from the source system.",
        "example": '(scope logic (and (project (= 2 2)) (project (= 3 3))))',
        "expected": "parent evaluates (= 2 2) → True, (= 3 3) → True; logic receives (and True True)",
        "patterns": [
            ";; Parent has =, logic has and. Project bridges the gap.\n"
            ";; Parent resolves (project (= 2 2)) → True before entering logic scope.\n"
            "(scope arithmetic (scope logic (and (project (= 2 2)) (project (= 3 3)))))",
            ";; Project a fact from parent into child scope\n"
            ";; Parent has my-fact=42. Child only has hash-leaf.\n"
            ";; Parent resolves (project my-fact) → 42, child sees (hash-leaf 42).\n"
            "(scope merkle (hash-leaf (project my-fact)))",
            ";; Project through nested scopes — each scope resolves its own projects\n"
            ";; arith resolves (project (+ a b)) → 10, then logic sees (and 10 True)\n"
            "(scope arith (scope logic (and (project (+ a b)) True)))",
            ";; Project with explicit named basis\n" '(scope evaluation (project search (in "engine.py" "def")))',
            ";; self is the default system with basic language operators\n"
            '(self (scope search (project (and bool1 bool2))))',
            ";; if works outside project (in scope) — if is a special form\n"
            '(scope search (if found (project (kind "diff")) "fallback"))',
            ";; Chain: project from self inside nested scope\n"
            '(scope search (and "class" (scope evaluation (project (or "query1" "query2")))))',
            ";; Nested project: outer project triggers scope, inner project injects parent value\n"
            ";; 1. parent hits project, evaluates its arg\n"
            ";; 2. arg is (scope child (hash (project my-fact)))\n"
            ";; 3. before entering child, parent resolves inner (project my-fact) → 42\n"
            ";; 4. child receives (hash 42), returns hash value\n"
            ";; 5. outer project yields that hash as concrete\n"
            "(project (scope child (hash (project my-fact))))",
        ],
    },
    DELEGATE: {
        "category": "special",
        "description": "Transport modifier — a happens-before operation where each scope "
        "in the chain eagerly evaluates a proposal and posts it to a :bind stack "
        "on the delegate expression. The DELEGATE handler then picks the result "
        "by depth (bare) or pattern match (conditional).\n\n"
        "Bare form: (delegate body) — every scope posts a proposal. Nesting "
        "(delegate (delegate body)) increases depth. The DELEGATE handler counts "
        "nesting depth and picks the Nth non-[] entry from closest.\n\n"
        "Conditional form: (delegate pattern body) — each scope binds ?-vars from "
        "its env (?name → env[name], ?_level → stack position, ?_self → result of "
        "evaluating body in the current engine). If pattern evaluates to true, body "
        "is evaluated and posted; otherwise [] is posted. The DELEGATE handler picks "
        "the first non-[] proposal from closest.\n\n"
        "?_self — self-resolution: at the innermost scope (where the delegate handler "
        "runs), ?_self is bound to the result of evaluating the body in the current "
        "engine. If the pattern references ?_self and the pattern passes, the delegate "
        "returns ?_self directly (self-resolution) before checking parent proposals. "
        "This allows a scope to handle the request itself when no parent can.\n\n"
        "Use (self expr) in delegate bodies to protect expr from the parent's rewriter. "
        "Each scope then evaluates the original expression in its own engine.\n\n"
        "The :bind stack is appended to the delegate expression as :bind (r1 r2 ...). "
        "Each scope adds one entry. [] means no match / not applicable.",
        "example": "(delegate (project store val))",
        "expected": "resolves store val at the caller's scope, not the current one",
        "patterns": [
            ";; Bare: skip one level, resolve at caller\n" "(delegate (project store val))",
            ";; Skip two levels\n" "(delegate (delegate (project store val)))",
            ";; At E in chain A→B→C→D→E:\n"
            ";; (project store val) → resolves at outermost (A)\n"
            ";; (delegate ...) → D's store (40)\n"
            ";; (delegate (delegate ...)) → C's store (30)\n"
            "(scope d (scope e (= (delegate (project store val)) 40)))",
            ";; Conditional: ?-var binds from each scope's env\n"
            ";; finds the scope where answer == 42\n"
            "(delegate (= ?answer 42) ?answer)",
            ";; Conditional with ?_level — binds to stack position\n"
            ";; routes to a specific depth in the scope chain\n"
            "(delegate (= ?_level 3) (scope signer (sign data)))",
            ";; ?_self gate — self-protected delegate routing\n"
            ";; each scope evaluates (self (solve ...)) in its own engine;\n"
            ";; ?_self = result. Closest scope where ?_self != unknown wins.\n"
            ";; If the innermost scope passes the gate, returns ?_self directly.\n"
            "(delegate (not (= ?_self unknown)) (self (solve ?domain ?x)))",
            ";; Delegation through isolated scope — ZK-style proof\n"
            ";; prover scope sees fact via delegate+project, only boolean crosses out\n"
            "(delegate (project age))",
        ],
    },
    SELF: {
        "category": "special",
        "description": "Evaluate expressions in the current engine. "
        "All arguments are evaluated normally in the calling engine's "
        "environment. Acts as the identity scope — useful inside "
        "scope-aware contexts where you want to stay in the current system.\n\n"
        "Rewriter boundary: the rewriter treats (self ...) as opaque and does "
        "not recurse into its contents. This makes (self expr) an evaluation "
        "boundary — expr is preserved until _eval processes it. Inside delegate "
        "bodies, (self expr) protects expr from the parent's rewriter so each "
        "scope evaluates the original expression in its own engine.",
        "example": '(self (and "def" "class"))',
        "expected": "result of evaluating (and \"def\" \"class\") in the current engine",
        "patterns": [
            ';; Evaluate in current engine\n' '(self (+ a b))',
            ';; Use self inside scope to stay in current system\n' '(scope self (and "def" "class"))',
            ';; Protect delegate body from parent rewriter — each scope evaluates in its own engine\n'
            '(delegate (not (= ?_self unknown)) (self (solve ?domain ?x)))',
        ],
    },
    SCOPE: {
        "category": "special",
        "description": "Evaluate expressions in a named scope. "
        "The first argument names the scope. If it is ``self``, "
        "the remaining expressions are evaluated in the current engine. "
        "Otherwise the name is resolved to a callable and the remaining "
        "arguments are passed unevaluated — the callable decides how "
        "to interpret them. The scope name is passed as the first "
        "argument to the callable. "
        "Exception: any (project ...) inside scope args is eagerly resolved "
        "by the current engine before forwarding. This is how the parent "
        "injects its own values into child scopes.",
        "example": '(scope evaluation (kind "diff"))',
        "expected": "result of calling the evaluation callable with \"evaluation\" and (kind \"diff\") unevaluated",
        "patterns": [
            ';; Query evaluation scope from search\n' '(scope evaluation (kind "diff"))',
            ';; Compose search and evaluation\n' '(and "def" (scope evaluation (category "issue")))',
            ';; Self-reference — evaluates in current engine\n' '(scope self (and "def" "class"))',
            ';; Project resolves before scope forwards — child gets concrete value\n'
            '(scope child (hash-leaf (project my-fact)))',
        ],
    },
    EQ: {
        "category": "special",
        "description": "Equality / rewrite operator.  Axioms of the form (= LHS RHS) "
        "are applied as left-to-right rewrite rules during evaluation.  "
        "The engine uses EQ structurally to identify rewrite rules, "
        "register value definitions, and trigger rewrite fallback "
        "when formal expressions cannot be compared directly.",
        "example": "(= (+ ?a ?b) (+ ?b ?a))",
        "expected": "rewrite rule (commutativity)",
        "patterns": [
            "(axiom add-identity (= (+ ?n zero) ?n)\n" '    :origin "Additive identity")',
            "(axiom add-commutative (= (+ ?a ?b) (+ ?b ?a))\n" '    :origin "Commutativity")',
        ],
    },
    # ----------------------------------------------------------
    # DSL directives
    # ----------------------------------------------------------
    AXIOM: {
        "category": "directive",
        "description": "Introduce a parametric rewrite rule as an axiom.  "
        "Axioms MUST contain at least one ?-variable — "
        "ground statements (no ?-variables) are rejected; "
        "use (fact ...) for values or (derive ...) for "
        "provable claims.  Axioms are instantiated later "
        "via :bind in a derive directive.",
        "example": '(axiom pos-rule (> ?x 0) :origin "manual")',
        "patterns": [
            # Simple parametric axiom with :origin
            '(axiom pos-rule (> ?x 0) :origin "manual")',
            # Parameterised axiom with structured evidence (apples demo)
            "(axiom add-identity (= (+ ?n zero) ?n)\n"
            '    :evidence (evidence "Counting Observations"\n'
            '      :quotes ("Adding nothing to a basket does not change the count")\n'
            '      :explanation "Additive identity: n + 0 = n"))',
            # Parameterised equality axiom (apples demo)
            "(axiom add-commutative (= (+ ?a ?b) (+ ?b ?a))\n"
            '    :evidence (evidence "Counting Observations"\n'
            '      :quotes ("The order of combining does not matter")\n'
            '      :explanation "Commutativity: a + b = b + a"))',
        ],
    },
    DEFTERM: {
        "category": "directive",
        "description": "Define a named term or concept.  Three forms:\n"
        "  1. Forward declaration (no body) — introduces a "
        "primitive symbol.\n"
        "  2. Computed expression — evaluates when referenced.\n"
        "  3. Conditional — uses (if ...) for branching logic.\n"
        "Terms resolve automatically when used in expressions.",
        "example": '(defterm total (+ a b) :origin "definition")',
        "patterns": [
            # Forward declaration / primitive symbol (apples demo)
            "(defterm zero\n"
            '    :evidence (evidence "Counting Observations"\n'
            '      :quotes ("An empty basket contains zero apples")\n'
            '      :explanation "Zero: the count of an empty collection"))',
            # Computed expression referencing other terms (apples demo)
            "(defterm morning-total (+ eve-morning adam-morning)\n"
            '    :evidence (evidence "Eden Inventory"\n'
            '      :quotes ("Combined morning harvest was 8 apples")\n'
            '      :explanation "Sum of Eve and Adam\'s morning picks"))',
            # Concrete value in successor notation (apples demo)
            "(defterm eve-morning (succ (succ (succ zero)))\n"
            '    :evidence (evidence "Eden Inventory"\n'
            '      :quotes ("Eve picked 3 apples from the east grove")\n'
            '      :explanation "Eve\'s morning count: SSS0"))',
            # Conditional definition (biomarkers demo)
            "(defterm clinical-utility\n"
            "    (if (and reliable-marker standalone-diagnostic)\n"
            '        "use-alone"\n'
            '        "use-with-confirmation")\n'
            '    :origin "Synthesized from both papers")',
            # Boolean-valued term (biomarkers demo)
            "(defterm reliable-marker\n"
            "    (> calprotectin-sensitivity 90)\n"
            '    :evidence (evidence "Paper A: Diagnostic"\n'
            '      :quotes ("Calprotectin is recommended as a first-line non-invasive test")\n'
            '      :explanation "Paper A recommends calprotectin as first-line test"))',
        ],
    },
    FACT: {
        "category": "directive",
        "description": "Set a ground truth value with evidence.  Facts are "
        "added to the evaluation environment so they resolve "
        "as values in expressions.  Use :origin for a plain "
        "string, or :evidence for a structured, quote-verified "
        "evidence block.",
        "example": '(fact revenue 15 :origin "Q3 report")',
        "patterns": [
            # Simple fact with :origin
            '(fact revenue 15 :origin "Q3 report")',
            # Fact with structured evidence (revenue demo)
            "(fact revenue-q3 15.0\n"
            '    :evidence (evidence "Q3 Report"\n'
            '      :quotes ("Q3 revenue was $15M")\n'
            '      :explanation "Dollar revenue figure from Q3 report"))',
            # Boolean fact (biomarkers demo)
            "(fact elevated-in-non-ibd true\n"
            '    :evidence (evidence "Paper B: Specificity"\n'
            '      :quotes ("Calprotectin is elevated in multiple non-IBD conditions")\n'
            '      :explanation "Calprotectin not specific to IBD"))',
            # Hypothetical fact for diff comparison
            "(fact calprotectin-specificity-optimistic 95\n"
            '    :origin "Hypothetical: what if combined approach achieved 95%?")',
        ],
    },
    DERIVE: {
        "category": "directive",
        "description": "Derive a theorem from existing axioms, facts, or "
        "terms listed in :using.  Evaluation is restricted to "
        ":using sources; dependencies of axioms and terms are "
        "expanded transitively.  Two modes:\n\n"
        "  1. Direct — provide an expression (WFF) to prove:\n"
        "     (derive name (expression) :using (sources...))\n"
        "     The second element is the WFF expression.\n\n"
        "  2. Instantiation — name a parameterised axiom and\n"
        "     supply :bind to substitute ?-variables:\n"
        "     (derive name axiom-name :bind ((?var val)...) :using (sources...))\n"
        "     The second element MUST be an axiom name (a symbol),\n"
        "     NOT an expression. :bind substitutes ?-variables in\n"
        "     the axiom's template. :using must include the axiom\n"
        "     name and all symbols referenced in :bind values.\n\n"
        "  IMPORTANT: Do NOT combine an inline expression with :bind.\n"
        "  If the expression is already ground (no ?-variables), use\n"
        "  mode 1 (direct) without :bind. :bind is ONLY for\n"
        "  instantiating a named axiom in mode 2.\n\n"
        "If any source has unverified evidence, the theorem is "
        'marked as a "potential fabrication".',
        "example": "(derive d1 (> x 0) :using (x))",
        "patterns": [
            # Direct derivation from facts (revenue demo)
            ";; Mode 1: Direct — WFF expression, no :bind\n"
            "(derive target-exceeded\n"
            "    (> revenue-q3-growth growth-target)\n"
            "    :using (revenue-q3-growth growth-target))",
            # Instantiation via :bind — single variable (apples demo)
            # :using must include axiom + symbols from :bind values
            ";; Mode 2: Instantiation — axiom name + :bind\n"
            "(derive three-plus-zero add-identity\n"
            "    :bind ((?n (succ (succ (succ zero)))))\n"
            "    :using (add-identity succ zero))",
            # Instantiation via :bind — multiple variables (apples demo)
            ";; Mode 2: Multiple :bind variables\n"
            "(derive morning-commutes add-commutative\n"
            "    :bind ((?a eve-morning) (?b adam-morning))\n"
            "    :using (add-commutative eve-morning adam-morning))",
            # Derivation showing fabrication propagation (revenue demo)
            ";; Fabrication propagation — unverified source taints the theorem\n"
            "(derive uses-fake\n    (> fake-metric 0)\n    :using (fake-metric))",
            # WRONG — common LLM mistake
            ";; WRONG — do NOT combine inline WFF with :bind:\n"
            ";; (derive d1 (<= x y) :bind ((?a x)) :using (ax1 x y))\n"
            ";; Use mode 1 (direct) or mode 2 (axiom name), never both.",
        ],
    },
    DIFF: {
        "category": "directive",
        "description": "Register a lazy comparison between two symbols.  "
        "When evaluated (via eval_diff or consistency), "
        "shows how all dependent terms diverge when :replace "
        "is swapped with :with.",
        "example": "(diff d1 :replace a :with b)",
        "patterns": [
            # Cross-source consistency check (revenue demo)
            "(diff growth-check\n    :replace revenue-q3-growth\n    :with revenue-q3-growth-computed)",
            # Hypothetical scenario (apples demo)
            "(diff eve-check\n    :replace eve-morning\n    :with eve-morning-alt)",
            # What-if analysis (biomarkers demo)
            "(diff specificity-check\n"
            "    :replace calprotectin-specificity\n"
            "    :with calprotectin-specificity-optimistic)",
        ],
    },
    EVIDENCE: {
        "category": "structural",
        "description": "Structured evidence block with verifiable quotes "
        "from a registered source document.  Quotes are "
        "checked against the document text; unverified "
        "quotes flag the statement and propagate through "
        "derivations.",
        "example": '(evidence "Doc" :quotes ("q1") :explanation "reason")',
        "patterns": [
            # Single quote (revenue demo)
            '(evidence "Q3 Report"\n'
            '    :quotes ("Q3 revenue was $15M")\n'
            '    :explanation "Dollar revenue figure from Q3 report")',
            # Multiple quotes (revenue demo)
            '(evidence "Bonus Policy Doc"\n'
            '    :quotes ("Bonus is 20% of base salary if growth target is exceeded"\n'
            '             "Eligibility requires that the quarterly revenue growth exceeds the stated annual growth target")\n'  # noqa: E501
            '    :explanation "Bonus calculation formula and eligibility criteria")',
        ],
    },
    # ----------------------------------------------------------
    # Pattern variables
    # ----------------------------------------------------------
    VAR_PREFIX: {
        "category": "structural",
        "description": "Pattern variable prefix.  Symbols starting with ? are "
        "pattern variables in expressions.  During matching, each "
        "?-variable binds to the corresponding sub-expression.  "
        "During substitution, bound values replace the variable.  "
        "Used in axioms (required), rewrite-rule theorems, and "
        ":bind clauses.",
        "example": "?x, ?n, ?pattern",
        "patterns": [
            "(axiom add-identity (= (+ ?n zero) ?n))",
            "(derive d1 ax1 :bind ((?x 42)))",
        ],
    },
    SPLAT_PREFIX: {
        "category": "structural",
        "description": "Splat/rest pattern prefix.  A ?...name symbol as the "
        "last element of a list pattern matches zero or more "
        "remaining elements as a list.  During substitution the "
        "bound list is spliced into the parent expression.  "
        "Enables variadic rewrite rules — e.g. recursive "
        "reduce/fold over arbitrary-length argument lists.",
        "example": "?...rest, ?...args, ?...tail",
        "patterns": [
            "; Variadic counting via recursive rewrite\n"
            "(axiom count-base (= (count-true) 0))\n"
            "(axiom count-step (= (count-true ?x ?...rest)\n"
            "    (+ (if ?x 1 0) (count-true ?...rest))))",
        ],
    },
    # ----------------------------------------------------------
    # Keyword arguments
    # ----------------------------------------------------------
    KW_QUOTES: {
        "category": "keyword",
        "description": "List of exact quotes from a registered source document.  Verified against the document text.",
        "example": ':quotes ("quote one" "quote two")',
    },
    KW_EXPLANATION: {
        "category": "keyword",
        "description": "Free-text explanation of why the quotes support the claim being made.",
        "example": ':explanation "revenue figure from Q3"',
    },
    KW_ORIGIN: {
        "category": "keyword",
        "description": "Plain-string origin for a fact/axiom/term.  Use "
        "when full evidence is not needed (e.g. hypotheticals, "
        "synthesised conclusions, manual entries).",
        "example": ':origin "Q3 report"',
    },
    KW_EVIDENCE: {
        "category": "keyword",
        "description": "Attach a structured evidence block to a directive.  "
        "Preferred over :origin when the claim should be "
        "quote-verified against a source document.",
        "example": ':evidence (evidence "Doc" :quotes ("q1") :explanation "x")',
    },
    KW_USING: {
        "category": "keyword",
        "description": "List of source names (axioms, facts, terms, or "
        "theorems) that a derivation depends on.  Required "
        "in derive directives.  Dependencies are expanded "
        "transitively — symbols referenced in axiom WFFs "
        "and term definitions are automatically included.  "
        "If any source has unverified evidence, the derived "
        "theorem inherits a fabrication taint.",
        "example": ":using (revenue-q3-growth growth-target)",
    },
    KW_REPLACE: {
        "category": "keyword",
        "description": "The symbol to substitute out in a diff.",
        "example": ":replace revenue-q3-growth",
    },
    KW_WITH: {
        "category": "keyword",
        "description": "The replacement symbol in a diff.",
        "example": ":with revenue-q3-growth-computed",
    },
    KW_BIND: {
        "category": "keyword",
        "description": "Bind ?-variables when instantiating a parameterised "
        "axiom or term in a derive directive.  Each binding "
        "is a (?var value) pair; values are expression trees, "
        "not evaluated results.",
        "example": ":bind ((?a eve-morning) (?b adam-morning))",
        "patterns": [
            # Single variable binding
            ":bind ((?n (succ (succ (succ zero)))))",
            # Multiple variable bindings
            ":bind ((?a eve-morning) (?b adam-morning))",
        ],
    },
}


# ============================================================
# Evidence Parsing
# ============================================================


def parse_evidence(expr) -> Evidence:
    """Parse an evidence s-expression into an Evidence object.

    Expected form:
      (evidence "document-name"
        :quotes ("quote 1" "quote 2")
        :explanation "why these quotes support the claim")
    """
    if not isinstance(expr, (list, tuple)) or not expr:
        raise SyntaxError(f"Invalid evidence expression: {expr}")

    if expr[0] != EVIDENCE:
        raise SyntaxError(f"Evidence expression must start with 'evidence', got: {expr[0]}")

    document = str(expr[1])
    quotes_raw = get_keyword(expr, KW_QUOTES, [])
    explanation = get_keyword(expr, KW_EXPLANATION, "")

    quotes = quotes_raw if isinstance(quotes_raw, (list, tuple)) else [str(quotes_raw)]
    quotes = [str(q) for q in quotes]

    return Evidence(document=document, quotes=quotes, explanation=explanation)


# ============================================================
# Keyword extraction
# ============================================================


def get_keyword(expr: Sentence, keyword: str, default=None):
    """Extract a keyword argument from an expression."""
    if not isinstance(expr, (list, tuple)):
        return default
    for i, item in enumerate(expr):
        if item == keyword and i + 1 < len(expr):
            return expr[i + 1]
    return default


# ============================================================
# Matcher — rewriting machinery
# ============================================================


def match(pattern: Sentence, expr: Sentence, bindings: dict | None = None) -> dict | None:
    """Match pattern against expr. ?-prefixed symbols are pattern variables.

    A ``?...name`` symbol as the last element of a list pattern matches
    zero or more remaining elements, bound as a list.
    """
    if bindings is None:
        bindings = {}
    if isinstance(pattern, Symbol) and str(pattern).startswith("?"):
        if pattern in bindings:
            return bindings if bindings[pattern] == expr else None
        return {**bindings, pattern: expr}
    if isinstance(pattern, (list, tuple)) and isinstance(expr, (list, tuple)):
        if pattern and isinstance(pattern[-1], Symbol) and str(pattern[-1]).startswith("?..."):
            splat = pattern[-1]
            fixed = pattern[:-1]
            if len(expr) < len(fixed):
                return None
            for p, e in zip(fixed, expr[: len(fixed)]):
                bindings = match(p, e, bindings)
                if bindings is None:
                    return None
            rest = expr[len(fixed) :]
            if splat in bindings:
                return bindings if bindings[splat] == rest else None
            return {**bindings, splat: rest}
        if len(pattern) != len(expr):
            return None
        for p, e in zip(pattern, expr):
            bindings = match(p, e, bindings)
            if bindings is None:
                return None
        return bindings
    if pattern == expr:
        return bindings
    return None


def free_vars(expr: Sentence) -> set[Symbol]:
    """Extract all ?-prefixed symbols from an expression."""
    if isinstance(expr, Symbol) and str(expr).startswith("?"):
        return {expr}
    if isinstance(expr, (list, tuple)):
        result: set[Symbol] = set()
        for sub in expr:
            result |= free_vars(sub)
        return result
    return set()


def substitute(expr: Sentence, bindings: dict) -> Sentence:
    """Replace symbols with their bound values in an expression tree.

    ``?...name`` bindings are spliced into the parent list rather than
    inserted as a nested list.
    """
    if isinstance(expr, Symbol) and expr in bindings:
        return bindings[expr]
    if isinstance(expr, (list, tuple)):
        result: list = []
        for sub in expr:
            if isinstance(sub, Symbol) and str(sub).startswith("?...") and sub in bindings:
                val = bindings[sub]
                if isinstance(val, (list, tuple)):
                    result.extend(val)
                else:
                    result.append(val)
            else:
                result.append(substitute(sub, bindings))
        return result
    return expr


# ============================================================
# Unfreezing — WFF (immutable tuples) → Sentence (mutable lists)
# ============================================================

# Directives whose bodies stay immutable (tuples from grammar)
_IMMUTABLE_DIRECTIVES = frozenset({AXIOM, FACT, EVIDENCE})
# Directives whose bodies become mutable (lists for rewriter)
_MUTABLE_DIRECTIVES = frozenset({DEFTERM, DERIVE})


def _unfreeze(wff: WFF) -> Sentence:
    """Convert tuple to list, recursing into children unless they must stay frozen."""
    if not isinstance(wff, tuple):
        return wff
    result = list(wff)
    for i, x in enumerate(result):
        if isinstance(x, tuple):
            if x and x[0] in _IMMUTABLE_DIRECTIVES:
                continue
            result[i] = _unfreeze(x)
    return result


def _unfreeze_selective(wff: WFF) -> Sentence:
    """Selectively unfreeze a top-level directive expression.

    Axioms, facts, evidence stay immutable (tuples).
    Defterms, derives become mutable (lists).
    Diffs are structural metadata — stay immutable.
    """
    if not isinstance(wff, tuple) or not wff:
        return wff
    head = wff[0]
    if head in _MUTABLE_DIRECTIVES:
        return _unfreeze(wff)
    if head in _IMMUTABLE_DIRECTIVES:
        return wff
    # Unknown directive or bare expression — unfreeze for evaluation
    return _unfreeze(wff)


# ============================================================
# Sentence Morphism — lang-level Morphism[str, list[AnnotatedSentence]]
# ============================================================


@dataclass
class SentenceIndex:
    """Pre-computed structural indices into a directive sentence.

    For ``(fact x 42 :origin "test")``:
        head=0, name=1, body=2, keywords={":origin": 4}

    Keyword values map keyword string → index of the *value* (not the key).
    """

    head: int = 0
    name: int | None = None
    body: int | None = None
    keywords: dict[str, int] = field(default_factory=dict)


def _index_sentence(expr) -> SentenceIndex:
    """Build a SentenceIndex from a sentence (list or tuple)."""
    idx = SentenceIndex()
    if not isinstance(expr, (list, tuple)) or not expr:
        return idx

    if len(expr) < 2:
        return idx

    idx.name = 1

    i = 2
    while i < len(expr):
        item = expr[i]
        if isinstance(item, str) and item.startswith(":"):
            if i + 1 < len(expr):
                idx.keywords[item] = i + 1
            i += 2
        else:
            if idx.body is None:
                idx.body = i
            i += 1

    return idx


@dataclass
class AnnotatedSentence:
    """A mutable sentence with provenance and structural index.

    expr:   mutable sentence (unfrozen from WFF)
    wff:    original immutable WFF from grammar (for inverse)
    line:   1-based source line
    order:  parse position within source
    index:  structural map (head, name, body, keyword positions)
    """

    expr: Sentence
    wff: WFF
    line: int
    order: int
    index: SentenceIndex


class SentenceMorphism:
    """Lang-level morphism: str → list[AnnotatedSentence].

    Wraps a StringMorphism.  For each AnnotatedWFF:
      1. Unfreezes the WFF into a mutable sentence
      2. Indexes the directive structure (head, name, body, keywords)

    The original immutable WFF is preserved for the inverse path.
    """

    def __init__(self, base: StringMorphism):
        self._base = base

    @property
    def grammar(self) -> Grammar[str]:
        return self._base.grammar

    def transform(self, source: str) -> list[AnnotatedSentence]:
        annotated_wffs = self._base.transform(source)
        result: list[AnnotatedSentence] = []
        for aw in annotated_wffs:
            expr = _unfreeze(aw.wff)
            index = _index_sentence(expr)
            result.append(
                AnnotatedSentence(
                    expr=expr,
                    wff=aw.wff,
                    line=aw.line,
                    order=aw.order,
                    index=index,
                )
            )
        return result

    def inverse(self, target: list[AnnotatedSentence]) -> str:
        return "\n".join(self.grammar.encode(a.wff) for a in target)


_sm = SentenceMorphism(base=_pm)


class ParseltongueSentenceMorphism:
    """Parseltongue sentence morphism — mutable sentences with structural index."""

    morphism = _sm

    @staticmethod
    def transform(source: str) -> list[AnnotatedSentence]:
        return _sm.transform(source)

    @staticmethod
    def inverse(target: list[AnnotatedSentence]) -> str:
        return _sm.inverse(target)


# ============================================================
# Translator Implementation — consumes SentenceMorphism
# ============================================================


class StringTranslator(Translator):
    """Translator backed by a SentenceMorphism."""

    def __init__(self, morphism: SentenceMorphism):
        self._morphism = morphism

    def translate(self, source: str) -> Sentence:
        annotated = self._morphism.transform(source)
        if not annotated:
            raise SyntaxError("Empty input")
        exprs = [_unfreeze_selective(a.wff) for a in annotated]
        if len(exprs) == 1:
            return exprs[0]
        return exprs


_parser = StringTranslator(morphism=_sm)


class PGStringParser:
    """Parseltongue string parser."""

    translator: Translator = _parser

    @staticmethod
    def translate(source: str) -> Sentence:
        return _parser.translate(source)
