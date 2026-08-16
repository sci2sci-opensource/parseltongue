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
class DocumentSource:
    """Evidence source: a single registered document."""

    name: str

    @property
    def display(self) -> str:
        return self.name


@dataclass(frozen=True)
class CorpusSource:
    """Evidence source: a corpus region — every classified file matching pattern."""

    pattern: str  # scope pattern, e.g. "src/auth"
    excludes: tuple[str, ...] = ()  # :except globs

    @property
    def display(self) -> str:
        return self.pattern


@dataclass(frozen=True)
class QuoteClaim:
    """Evidence claim grounded by being FOUND in the source."""

    text: str

    @property
    def display(self) -> str:
        return self.text


@dataclass(frozen=True)
class QueryClaim:
    """Evidence claim quantified over every match of a search query in the source.

    polarity "absent": the query must have zero matches.
    polarity "forall": every match must satisfy the companion condition.
    """

    query: str  # search s-expression, source text
    polarity: str = "absent"  # "absent" | "forall"
    satisfies: str | None = None  # companion condition (:forall only)

    @property
    def display(self) -> str:
        return self.query


EVIDENCE_TYPE_DOC_QUOTE = "doc_quote"
EVIDENCE_TYPE_CORPUS_QUERY = "corpus_query"


@dataclass(frozen=True, init=False)
class Evidence:
    """Structured evidence: typed claims about a typed source.

    ``type`` says how the instance is parsed and which verifier structure
    applies. The default, "doc_quote", is the classic form — verbatim quotes
    from a registered document. The language does not prescribe the
    verification algorithm; whichever layer can ground a given type fills
    ``verification`` and flips ``verified``.

    ``document`` and ``quotes`` are interface-preserving views over the
    typed interior, and the legacy constructor signature still works:
    ``Evidence(document=..., quotes=..., explanation=...)``.
    """

    source: "DocumentSource | CorpusSource"
    claims: "tuple[QuoteClaim | QueryClaim, ...]"
    explanation: str = ""  # why this evidence supports the claim
    type: str = EVIDENCE_TYPE_DOC_QUOTE  # discriminator: parse + verifier structure
    verification: list = field(default_factory=list)  # filled by verifier
    verified: bool = False  # claims verified?
    verify_manual: bool = False  # manually verified by user?
    signature: str | None = None  # who verified — set by verify_manual

    def __init__(
        self,
        document=None,
        quotes=None,
        explanation: str = "",
        verification: list | None = None,
        verified: bool = False,
        verify_manual: bool = False,
        signature: "str | None" = None,
        source: "DocumentSource | CorpusSource | None" = None,
        claims: "tuple[QuoteClaim | QueryClaim, ...] | None" = None,
        type: str = EVIDENCE_TYPE_DOC_QUOTE,
    ):
        if source is None:
            source = DocumentSource(name=str(document) if document is not None else "")
        if claims is None:
            claims = tuple(QuoteClaim(text=str(q)) for q in (quotes or []))
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "claims", tuple(claims))
        object.__setattr__(self, "explanation", explanation)
        object.__setattr__(self, "type", type)
        object.__setattr__(self, "verification", list(verification) if verification is not None else [])
        object.__setattr__(self, "verified", verified)
        object.__setattr__(self, "verify_manual", verify_manual)
        object.__setattr__(self, "signature", signature)

    @property
    def document(self) -> str:
        """Interface-preserving view: the source's display string."""
        return self.source.display

    @property
    def quotes(self) -> list[str]:
        """Interface-preserving view: each claim's display string."""
        return [c.display for c in self.claims]

    @property
    def is_grounded(self) -> bool:
        """Evidence is grounded if verified or manually verified."""
        return self.verified or self.verify_manual

    def __str__(self):
        status = "grounded" if self.is_grounded else "UNVERIFIED"
        tag = "evidence" if self.type == EVIDENCE_TYPE_DOC_QUOTE else f"evidence/{self.type}"
        return f"[{tag}: {self.document} ({status})]"


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
