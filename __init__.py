"""
Parseltongue — a DSL for formal systems with evidence grounding.

Quick start::

    from parseltongue import System, load_source, Symbol

    s = System()
    load_source(s, '(fact x 5 :origin "manual")')
"""

from .core import (                                # noqa: F401
    # Types & reader
    Symbol, Evidence, Axiom, Theorem, Term,
    parse, parse_all, to_sexp,
    match, free_vars, substitute, get_keyword,
    # Language constants
    IF, LET,
    AXIOM, DEFTERM, FACT, DERIVE, DIFF, EVIDENCE,
    KW_QUOTES, KW_EXPLANATION, KW_ORIGIN, KW_EVIDENCE,
    KW_USING, KW_REPLACE, KW_WITH, KW_BIND,
    LANG_DOCS, parse_evidence,
    # Engine
    System, load_source,
    DEFAULT_OPERATORS, ENGINE_DOCS,
    ADD, SUB, MUL, DIV, MOD,
    GT, LT, GE, LE, EQ, NE,
    AND, OR, NOT, IMPLIES,
    DiffResult, ConsistencyIssue, ConsistencyWarning, ConsistencyReport,
)
