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
from .llm import OpenRouterProvider, Pipeline  # noqa: F401
