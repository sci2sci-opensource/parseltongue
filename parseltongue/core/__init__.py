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

# Default operators & docs
from .default_system_settings import (  # noqa: F401
    ADD,
    AND,
    ARITHMETIC_OPS,
    COMPARISON_OPS,
    DEFAULT_OPERATORS,
    DIV,
    ENGINE_DOCS,
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
)

# Engine types
from .engine import (  # noqa: F401
    ConsistencyIssue,
    ConsistencyReport,
    ConsistencyWarning,
    DiffResult,
    Fact,
)

# Language constants & evidence parsing
from .lang import (  # noqa: F401
    AXIOM,
    DEFTERM,
    DERIVE,
    DIFF,
    DSL_KEYWORDS,
    EQ,
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

# System & loader
from .system import System, load_source  # noqa: F401
