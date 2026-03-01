"""
Parseltongue Core — public API.

Import the DSL primitives directly from this package::

    from core import System, load_source, Symbol, Evidence
    from core import parse, parse_all, to_sexp
"""

# Types & reader
from .atoms import (  # noqa: F401
    Axiom,
    Evidence,
    Symbol,
    Term,
    Theorem,
    atom,
    free_vars,
    get_keyword,
    match,
    parse,
    parse_all,
    read_tokens,
    substitute,
    to_sexp,
    tokenize,
)

# Engine & loader
from .engine import (  # noqa: F401
    ADD,
    AND,
    ARITHMETIC_OPS,
    COMPARISON_OPS,
    DEFAULT_OPERATORS,
    DIV,
    ENGINE_DOCS,
    EQ,
    GE,
    GT,
    IMPLIES,
    LE,
    LOGIC_OPS,
    LT,
    MOD,
    MUL,
    NE,
    NOT,
    OR,
    SUB,
    ConsistencyIssue,
    ConsistencyReport,
    ConsistencyWarning,
    DiffResult,
    System,
    load_source,
)

# Language constants & evidence parsing
from .lang import (  # noqa: F401
    AXIOM,
    DEFTERM,
    DERIVE,
    DIFF,
    DSL_KEYWORDS,
    EVIDENCE,
    FACT,
    IF,
    KW_BIND,
    KW_EVIDENCE,
    KW_EXPLANATION,
    KW_ORIGIN,
    KW_QUOTES,
    KW_REPLACE,
    KW_USING,
    KW_WITH,
    LANG_DOCS,
    LET,
    SPECIAL_FORMS,
    parse_evidence,
)
