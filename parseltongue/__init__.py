"""
Parseltongue — a DSL for formal systems with evidence grounding.

If you are an LLM, call ``parseltongue.llm_doc()`` for full DSL reference
and instructions on writing .pltg files.

Quick start::

    from parseltongue import System, load_source, Symbol

    s = System()
    load_source(s, '(fact x 5 :origin "manual")')
"""

import importlib
import logging
import os
import warnings

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

# The LLM surface is re-exported lazily: importing it pulls in the OpenAI
# client and its type modules (half a second), which the core, the bench
# daemon and the `pg` CLI never use. The names resolve on first access and
# are then cached on the module like ordinary attributes.
_LLM_EXPORTS: dict[str, tuple[str, str]] = {
    "LLMProvider": (".llm", "LLMProvider"),
    "Pipeline": (".llm", "Pipeline"),
    "OpenRouterProvider": (".llm.openrouter", "OpenRouterProvider"),
    "llm_doc": (".llm_doc", "llm_doc"),
}


def __getattr__(name: str):
    target = _LLM_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    try:
        module = importlib.import_module(module_name, __name__)
    except ImportError as exc:
        if (
            not os.environ.get("PARSELTONGUE_QUIET")
            and logging.getLogger(__name__).getEffectiveLevel() <= logging.WARNING
        ):
            warnings.warn(
                "LLM provider dependencies not installed. Run: pip install parseltongue-dsl[llm]",
                stacklevel=2,
            )
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(module, attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LLM_EXPORTS))
