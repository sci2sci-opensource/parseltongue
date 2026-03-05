"""
Parseltongue — a DSL for formal systems with evidence grounding.

Quick start::

    from parseltongue import System, load_source, Symbol

    s = System()
    load_source(s, '(fact x 5 :origin "manual")')
"""

from .core import (  # noqa: F401
    ADD,
    AND,
    AXIOM,
    DEFAULT_OPERATORS,
    DEFTERM,
    DERIVE,
    DIFF,
    DIV,
    ENGINE_DOCS,
    EQ,
    EVIDENCE,
    FACT,
    GE,
    GT,
    # Language constants
    IF,
    IMPLIES,
    KW_BIND,
    KW_EVIDENCE,
    KW_EXPLANATION,
    KW_ORIGIN,
    KW_QUOTES,
    KW_REPLACE,
    KW_USING,
    KW_WITH,
    LANG_DOCS,
    LE,
    LET,
    LT,
    MOD,
    MUL,
    NE,
    NOT,
    OR,
    SUB,
    Axiom,
    ConsistencyIssue,
    ConsistencyReport,
    ConsistencyWarning,
    DiffResult,
    Evidence,
    # Types & reader
    Symbol,
    # Engine
    System,
    Term,
    Theorem,
    free_vars,
    get_keyword,
    load_source,
    match,
    parse,
    parse_all,
    parse_evidence,
    substitute,
    to_sexp,
)
from .core import load_pltg as load_main  # noqa: F401
from .llm import LLMProvider, Pipeline  # noqa: F401

try:
    from .llm.openrouter import OpenRouterProvider  # noqa: F401
except ImportError:
    import warnings

    warnings.warn(
        "LLM provider dependencies not installed. Run: pip install parseltongue-dsl[llm]",
        stacklevel=2,
    )
