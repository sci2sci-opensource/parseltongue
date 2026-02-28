"""
Parseltongue DSL — Language Core.

Language grammar symbols, keyword constants, documentation registry,
and evidence parsing.  Imports and re-exports everything from atoms
for backward compatibility.
"""

from atoms import (                          # noqa: F401 — re-export
    Symbol, Evidence, Axiom, Term,
    tokenize, read_tokens, atom,
    parse, parse_all, to_sexp,
    get_keyword,
)


# ============================================================
# Language-Level Symbol Constants
# ============================================================

# Special forms — evaluated directly by the interpreter, not via env
IF    = Symbol('if')
LET   = Symbol('let')
QUOTE = Symbol('quote')

# DSL keywords — structural symbols of the language
AXIOM    = Symbol('axiom')
DEFTERM  = Symbol('defterm')
FACT     = Symbol('fact')
DERIVE   = Symbol('derive')
DIFF     = Symbol('diff')
EVIDENCE = Symbol('evidence')

SPECIAL_FORMS = (IF, LET, QUOTE)
DSL_KEYWORDS  = (AXIOM, DEFTERM, FACT, DERIVE, DIFF, EVIDENCE)

# Keyword arguments (plain strings, not Symbols — returned by atom() as-is)
KW_QUOTES      = ':quotes'
KW_EXPLANATION = ':explanation'
KW_ORIGIN      = ':origin'
KW_EVIDENCE    = ':evidence'
KW_USING       = ':using'
KW_REPLACE     = ':replace'
KW_WITH        = ':with'


# ============================================================
# Language Documentation
# ============================================================

LANG_DOCS = {
    # Special forms
    IF: {
        'category': 'special',
        'description': 'Conditional evaluation. Evaluates the then-branch '
                       'if condition is true, else-branch otherwise.',
        'example': '(if (> x 0) "positive" "non-positive")',
        'expected': '"positive" (when x > 0)',
    },
    LET: {
        'category': 'special',
        'description': 'Local bindings. Binds names to values in a local '
                       'scope, then evaluates the body.',
        'example': '(let ((x 10)) (+ x 5))',
        'expected': 15,
    },
    QUOTE: {
        'category': 'special',
        'description': 'Return the s-expression without evaluating it.',
        'example': '(quote (+ 1 2))',
        'expected': '(+ 1 2)',
    },

    # DSL directives
    AXIOM: {
        'category': 'directive',
        'description': 'Introduce a well-formed formula with evidence.',
        'example': '(axiom a1 (> x 0) :origin "manual")',
    },
    DEFTERM: {
        'category': 'directive',
        'description': 'Define a named term/concept.',
        'example': '(defterm total (+ a b) :origin "definition")',
    },
    FACT: {
        'category': 'directive',
        'description': 'Set a ground truth value with evidence.',
        'example': '(fact revenue 15 :origin "Q3 report")',
    },
    DERIVE: {
        'category': 'directive',
        'description': 'Derive a statement from existing axioms/facts.',
        'example': '(derive d1 (> x 0) :using (x))',
    },
    DIFF: {
        'category': 'directive',
        'description': 'Register a lazy comparison between two symbols.',
        'example': '(diff d1 :replace a :with b)',
    },
    EVIDENCE: {
        'category': 'structural',
        'description': 'Structured evidence with verifiable quotes '
                       'from a source document.',
        'example': '(evidence "Doc" :quotes ("q1") :explanation "reason")',
    },

    # Keyword arguments
    KW_QUOTES: {
        'category': 'keyword',
        'description': 'List of exact quotes from a source document.',
        'example': ':quotes ("quote one" "quote two")',
    },
    KW_EXPLANATION: {
        'category': 'keyword',
        'description': 'Why the quotes support the claim.',
        'example': ':explanation "revenue figure from Q3"',
    },
    KW_ORIGIN: {
        'category': 'keyword',
        'description': 'Plain-string origin for a fact/axiom/term.',
        'example': ':origin "Q3 report"',
    },
    KW_EVIDENCE: {
        'category': 'keyword',
        'description': 'Structured evidence block for a directive.',
        'example': ':evidence (evidence "Doc" :quotes ("q1") '
                   ':explanation "x")',
    },
    KW_USING: {
        'category': 'keyword',
        'description': 'List of axioms/facts used in derivation.',
        'example': ':using (ax1 fact2)',
    },
    KW_REPLACE: {
        'category': 'keyword',
        'description': 'Symbol to substitute in a diff.',
        'example': ':replace growth',
    },
    KW_WITH: {
        'category': 'keyword',
        'description': 'Replacement symbol in a diff.',
        'example': ':with alt_growth',
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
        raise SyntaxError(
            f"Evidence expression must start with 'evidence', got: {expr[0]}")

    document = str(expr[1])
    quotes_raw = get_keyword(expr, KW_QUOTES, [])
    explanation = get_keyword(expr, KW_EXPLANATION, '')

    quotes = quotes_raw if isinstance(quotes_raw, list) else [str(quotes_raw)]
    quotes = [str(q) for q in quotes]

    return Evidence(document=document, quotes=quotes, explanation=explanation)
