"""
Parseltongue DSL — Atoms.

Pure types. No grammar, no domain knowledge, no state.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

# ============================================================
# Fundamental Types
# ============================================================
from typing import TypeAlias


class Silence(Sequence):
    """The empty expression — an irreducible atom. Singleton.

    Silence is its own instance. Indexing silence returns silence.
    Iterating over silence yields nothing. Silence is silence all the way down.
    """

    __slots__ = ()

    def __new__(cls):
        try:
            return SILENCE
        except NameError:
            return super().__new__(cls)

    def __getitem__(self, index):
        return self

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __repr__(self):
        return "()"

    def __bool__(self):
        return False


class Symbol(str):
    """A symbol in Parseltongue. Just a string with a distinct type."""

    def __repr__(self):
        return f"'{self}"


SILENCE = Silence()

Primitive: TypeAlias = str | int | float | bool | Silence
WFF: TypeAlias = Symbol | Primitive | Sequence["WFF"]


import warnings as _warnings
from typing import Any, Literal, overload


# ============================================================
# Grammar re-exports (canonical home: grammar.py)
# ============================================================
#
# TODO: CIRCULAR DEPENDENCY — atoms ↔ grammar
#
# Atoms is the foundation layer (pure types, no behavior). Grammar depends
# on atoms for Symbol/Silence/WFF — that's correct. But atoms imports back
# from grammar for: (1) __str__ display on Axiom/Theorem/Term, (2) backward-
# compat re-exports, (3) deprecated parse/parse_all wrappers.
#
# This works at runtime because Python resolves the cycle — all types grammar
# needs are defined above this line. But architecturally atoms should depend
# on nothing. Rethinking the display layer (__str__) would break the cycle;
# the re-exports and deprecations can be removed once callers migrate.
#
@overload
def tokenize(source: str, *, track_lines: Literal[False] = ...) -> list[str]: ...
@overload
def tokenize(source: str, *, track_lines: Literal[True]) -> tuple[list[str], list[int]]: ...
def tokenize(source: str, *, track_lines: bool = False) -> list[str] | tuple[list[str], list[int]]:
    from .grammar import tokenize as _tokenize

    return _tokenize(source, track_lines=track_lines)


def read_tokens(tokens: list[str]):
    """Backward-compat: unfreezes grammar's immutable result."""
    # TODO: fill in unfreeze logic
    return _read_tokens_immutable(tokens)


from .grammar import ParseltongueGrammar  # noqa: E402


def atom(token: str):
    raise SyntaxError("should've not been accessed")


from .grammar import read_tokens as _read_tokens_immutable  # noqa: E402


def parse(source: str) -> Any:
    """Parse a source string into an s-expression."""
    tokens = tokenize(source)
    return read_tokens(tokens)


def parse(source: str):
    """Deprecated: use PGStringParser.translate()."""
    _warnings.warn("parse() is deprecated, use PGStringParser.translate()", DeprecationWarning, stacklevel=2)
    from .lang import PGStringParser

    return PGStringParser.translate(source)


def parse_all(source: str) -> list:
    """Deprecated: use PGStringParser.translate()."""
    _warnings.warn("parse_all() is deprecated, use PGStringParser.translate()", DeprecationWarning, stacklevel=2)
    from .lang import PGStringParser

    result = PGStringParser.translate(source)
    if isinstance(result, (list, tuple)) and result and isinstance(result[0], (list, tuple)):
        return result
    return [result]


def to_sexp(obj) -> str:
    from .grammar import to_sexp as g_sexp  # noqa: F401, E402

    return g_sexp(obj)


# ============================================================
# Data Structures
# ============================================================


def _origin_tag(origin) -> str:
    if isinstance(origin, Evidence):
        return str(origin)
    return f"[origin: {origin}]"


@dataclass(frozen=True)
class Evidence:
    """Structured evidence with verifiable quotes from a source document."""

    document: str  # registered document name
    quotes: list[str]  # exact quotes from the document
    explanation: str = ""  # why these quotes support the claim
    verification: list = field(default_factory=list)  # filled by verifier
    verified: bool = False  # all quotes verified?
    verify_manual: bool = False  # manually verified by user?

    @property
    def is_grounded(self) -> bool:
        """Evidence is grounded if verified or manually verified."""
        return self.verified or self.verify_manual

    def __str__(self):
        status = "grounded" if self.is_grounded else "UNVERIFIED"
        return f"[evidence: {self.document} ({status})]"


@dataclass(frozen=True)
class Axiom:
    """An axiom: a foundational WFF assumed true, with evidence.

    Every axiom carries a wff (never None).
    """

    name: str
    wff: WFF
    origin: "str | Evidence"

    def __str__(self):
        # TODO: __str__ couples atoms to grammar — rethink display layer
        return f"{self.name}: {ParseltongueGrammar.enc(self.wff)} {_origin_tag(self.origin)}"


@dataclass(frozen=True)
class Theorem:
    """A theorem: a WFF derived from facts, axioms, terms, or other theorems.

    Every theorem carries a wff (never None).
    """

    name: str
    wff: WFF
    derivation: list = field(default_factory=list)
    origin: "str | Evidence" = "derived"

    def __str__(self):
        # TODO: __str__ couples atoms to grammar — rethink display layer
        tag = f"[derived from: {', '.join(self.derivation)}]"
        return f"{self.name}: {ParseltongueGrammar.enc(self.wff)} {tag}"


@dataclass(frozen=True)
class Term:
    """A term/concept/primitive introduced into the system.

    Has two modes: primitive (definition is None) or computed (definition is not None).
    """

    name: str
    definition: WFF | None
    origin: "str | Evidence"

    def __str__(self):
        # TODO: __str__ couples atoms to grammar — rethink display layer
        defn = ParseltongueGrammar.enc(self.definition) if self.definition is not None else "(primitive)"
        return f"{self.name}: {defn} {_origin_tag(self.origin)}"


# ============================================================
# Deprecated — use grammar.py or lang.py directly
# ============================================================


def get_keyword(expr, keyword, default=None):
    """Deprecated: use lang.get_keyword()."""
    _warnings.warn("atoms.get_keyword() is deprecated, use lang.get_keyword()", DeprecationWarning, stacklevel=2)
    from .lang import get_keyword as _get_keyword

    return _get_keyword(expr, keyword, default)


def match(pattern, expr, bindings=None):
    """Deprecated: use lang.match()."""
    _warnings.warn("atoms.match() is deprecated, use lang.match()", DeprecationWarning, stacklevel=2)
    from .lang import match as _match

    return _match(pattern, expr, bindings)


def free_vars(expr) -> set:
    """Deprecated: use lang.free_vars()."""
    _warnings.warn("atoms.free_vars() is deprecated, use lang.free_vars()", DeprecationWarning, stacklevel=2)
    from .lang import free_vars as _free_vars

    return _free_vars(expr)


def substitute(expr, bindings: dict):
    """Deprecated: use lang.substitute()."""
    _warnings.warn("atoms.substitute() is deprecated, use lang.substitute()", DeprecationWarning, stacklevel=2)
    from .lang import substitute as _substitute

    return _substitute(expr, bindings)
