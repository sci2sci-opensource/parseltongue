"""
Parseltongue Core — public API.

Import the DSL primitives directly from this package::

    from core import System, load_source, Symbol, Evidence
    from core import parse, parse_all, to_sexp
"""

# Types & reader
from .atoms import (                               # noqa: F401
    Symbol, Evidence, Axiom, Theorem, Term,
    tokenize, read_tokens, atom,
    parse, parse_all, to_sexp,
    match, free_vars, substitute, get_keyword,
)

# Language constants & evidence parsing
from .lang import (                                # noqa: F401
    IF, LET,
    AXIOM, DEFTERM, FACT, DERIVE, DIFF, EVIDENCE,
    SPECIAL_FORMS, DSL_KEYWORDS,
    KW_QUOTES, KW_EXPLANATION, KW_ORIGIN, KW_EVIDENCE,
    KW_USING, KW_REPLACE, KW_WITH, KW_BIND,
    LANG_DOCS, parse_evidence,
)

# Engine & loader
from .engine import (                              # noqa: F401
    System, load_source,
    DEFAULT_OPERATORS, ENGINE_DOCS,
    ADD, SUB, MUL, DIV, MOD,
    GT, LT, GE, LE, EQ, NE,
    AND, OR, NOT, IMPLIES,
    ARITHMETIC_OPS, COMPARISON_OPS, LOGIC_OPS,
    DiffResult, ConsistencyIssue, ConsistencyWarning, ConsistencyReport,
)
