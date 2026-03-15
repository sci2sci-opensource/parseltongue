"""
Parseltongue Core — public API.

Import the DSL primitives directly from this package::

    from core import System, load_source, Symbol, Evidence
    from core import parse, parse_all, to_sexp
"""

# Types
from .atoms import (  # noqa: F401
    Axiom,
    Evidence,
    Symbol,
    Term,
    Theorem,
    free_vars,
    get_keyword,
    match,
    parse,
    parse_all,
    substitute,
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

# Grammar
from .grammar import atom, read_tokens, to_sexp, tokenize  # noqa: F401

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
    QUOTE,
    SPECIAL_FORMS,
    parse_evidence,
)
from .loader import Context, Loader, LoaderContext, ModuleContext, load_pltg  # noqa: F401

# System & loader
from .system import AbstractSystem, DefaultSystem, EmptySystem, System, load_source  # noqa: F401
