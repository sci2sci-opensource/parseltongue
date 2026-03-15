"""
Parseltongue DSL — Morphism.

Annotated bidirectional maps backed by a Grammar.  A morphism transforms
a source representation R into an enriched target T that carries both
the decoded WFF *and* provenance metadata from R.  The inverse extracts
the WFF from T and encodes it back to R through the grammar.

    Grammar[R]:       R ↔ WFF        (pure codec)
    Morphism[R, T]:   R ↔ T          (annotated map, backed by Grammar)
    Translator:       str → Sentence  (meaning layer, can consume T)

The round-trip R → T → R loses annotations (they came from R).
The round-trip T → R → T re-derives them from the source.
"""

from dataclasses import dataclass
from typing import Protocol, TypeVar

from .atoms import WFF
from .grammar import Grammar, read_tokens, tokenize

R = TypeVar("R")
T = TypeVar("T")


# ============================================================
# Morphism Protocol
# ============================================================


class Morphism(Protocol[R, T]):
    """Bidirectional annotated map backed by a Grammar.

    transform:  R → T   (decode + annotate with source metadata)
    inverse:    T → R   (extract WFF from T → encode back to R)
    """

    @property
    def grammar(self) -> Grammar[R]: ...

    def transform(self, source: R) -> T: ...
    def inverse(self, target: T) -> R: ...


# ============================================================
# Annotated Sentence — the T for string morphisms
# ============================================================


@dataclass
class AnnotatedWFF:
    """A WFF with provenance metadata from the source string.

    The wff is an immutable tuple straight from the grammar.
    The line is the 1-based source line where the expression started.
    The order is the parse position within the source.
    """

    wff: WFF
    line: int
    order: int


# ============================================================
# String Morphism — Morphism[str, list[AnnotatedWFF]]
# ============================================================


class StringMorphism:
    """Morphism[str, list[AnnotatedWFF]] — string source to annotated WFFs.

    Forward:  tokenize with line tracking, parse each expression,
              wrap in AnnotatedWFF with line and order metadata.
    Inverse:  extract WFFs, encode each back to string via grammar.
    """

    def __init__(self, grammar: Grammar[str]):
        self.grammar = grammar

    def transform(self, source: str) -> list[AnnotatedWFF]:
        tokens, lines = tokenize(source, track_lines=True)
        result: list[AnnotatedWFF] = []
        self.parse_errors: list[tuple[int, SyntaxError]] = []
        order = 0
        while tokens:
            line = lines[0]
            pre = len(tokens)
            try:
                wff = read_tokens(tokens)
            except SyntaxError as e:
                self.parse_errors.append((line, e))
                break
            del lines[: pre - len(tokens)]
            result.append(AnnotatedWFF(wff=wff, line=line, order=order))
            order += 1
        return result

    def inverse(self, target: list[AnnotatedWFF]) -> str:
        return "\n".join(self.grammar.encode(a.wff) for a in target)


# ============================================================
# Parseltongue Morphism — singleton + static access
# ============================================================


from .grammar import _pg  # noqa: E402

_pm = StringMorphism(grammar=_pg)


class ParseltongueMorphism:
    """Parseltongue string morphism — annotated WFFs with line provenance."""

    morphism: Morphism[str, list[AnnotatedWFF]] = _pm

    @staticmethod
    def transform(source: str) -> list[AnnotatedWFF]:
        return _pm.transform(source)

    @staticmethod
    def inverse(target: list[AnnotatedWFF]) -> str:
        return _pm.inverse(target)
