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

Evidence can be attached to any directive via :origin (plain string) or
:evidence (structured block with verifiable :quotes and :explanation).

See LANG_DOCS below for full syntax and examples drawn from real demos.
"""

from .atoms import (  # noqa: F401 — re-export
    Axiom,
    Evidence,
    Symbol,
    Term,
    Theorem,
    atom,
    get_keyword,
    parse,
    parse_all,
    read_tokens,
    to_sexp,
    tokenize,
)

# ============================================================
# Language-Level Symbol Constants
# ============================================================

# Special forms — evaluated directly by the interpreter, not via env
IF = Symbol("if")
LET = Symbol("let")
EQ = Symbol("=")
QUOTE = Symbol("quote")

# DSL keywords — structural symbols of the language
AXIOM = Symbol("axiom")
DEFTERM = Symbol("defterm")
FACT = Symbol("fact")
DERIVE = Symbol("derive")
DIFF = Symbol("diff")
EVIDENCE = Symbol("evidence")

SPECIAL_FORMS = (IF, LET, QUOTE)
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
    if not isinstance(expr, list) or not expr:
        raise SyntaxError(f"Invalid evidence expression: {expr}")

    if expr[0] != EVIDENCE:
        raise SyntaxError(f"Evidence expression must start with 'evidence', got: {expr[0]}")

    document = str(expr[1])
    quotes_raw = get_keyword(expr, KW_QUOTES, [])
    explanation = get_keyword(expr, KW_EXPLANATION, "")

    quotes = quotes_raw if isinstance(quotes_raw, list) else [str(quotes_raw)]
    quotes = [str(q) for q in quotes]

    return Evidence(document=document, quotes=quotes, explanation=explanation)
