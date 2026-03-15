"""
Parseltongue Core — public API.

Import the DSL primitives directly from this package::

    from core import System, load_source, Symbol, Evidence
"""

# Types
from .atoms import (  # noqa: F401
    Axiom,
    Evidence,
    Symbol,
    Term,
    Theorem,
)

# Language functions (canonical home: lang.py)
from .lang import (  # noqa: F401
    PGStringParser,
    free_vars,
    get_keyword,
    match,
    substitute,
)

# Backward-compat aliases — canonical is PGStringParser.translate
parse = PGStringParser.translate


def parse_all(source: str) -> list:
    """Parse source into a list of top-level expressions."""
    result = PGStringParser.translate(source)
    if isinstance(result, (list, tuple)) and result and isinstance(result[0], (list, tuple)):
        return list(result)
    return [result] if result else []


# Default operators & docs
from .default_system_settings import (  # noqa: F401, E402
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
from .engine import (  # noqa: F401,  E402
    ConsistencyIssue,
    ConsistencyReport,
    ConsistencyWarning,
    DiffResult,
    Fact,
)

# Grammar
from .grammar import atom, read_tokens, to_sexp, tokenize  # noqa: F401, E402

# Language constants & evidence parsing
from .lang import (  # noqa: F401, E402
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
from .loader import Context, Loader, LoaderContext, ModuleContext, load_pltg  # noqa: F401, E402

# System & loader
from .system import AbstractSystem, DefaultSystem, EmptySystem, System, load_source  # noqa: F401, E402
