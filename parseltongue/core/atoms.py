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


# CIRCULAR DEPENDENCY NOTE — atoms ↔ grammar
# Atoms is the foundation layer (pure types, no behavior). Grammar depends
# on atoms for Symbol/Silence/WFF — that's correct. The only back-import
# is ParseltongueGrammar for __str__ display on Axiom/Theorem/Term.
from .grammar import ParseltongueGrammar  # noqa: E402

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
