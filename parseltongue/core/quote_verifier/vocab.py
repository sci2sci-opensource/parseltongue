"""Vocab — the term dictionary shared by every index over one corpus.

Terms (normalized words, stems, compound parts) are interned once and
referenced everywhere else by a 32-bit id. Per-document structures then
hold ``array('I')`` of ids instead of dicts keyed by repeated strings.

Append-only: an id never changes meaning for the lifetime of the Vocab,
so readers holding id arrays stay valid while an indexer thread adds
terms. ``id()`` appends to the list before publishing the dict entry, so
a concurrent ``term(i)`` for a freshly published id always resolves.
"""

from __future__ import annotations

from array import array
from collections.abc import Iterable

from .posmap import U32


class Vocab:
    __slots__ = ("_terms", "_ids")

    def __init__(self, terms: Iterable[str] = ()):
        self._terms: list[str] = list(terms)
        self._ids: dict[str, int] = {t: i for i, t in enumerate(self._terms)}

    def id(self, term: str) -> int:
        """Id for *term*, assigning the next one if unseen."""
        i = self._ids.get(term)
        if i is None:
            i = len(self._terms)
            self._terms.append(term)
            self._ids[term] = i
        return i

    def lookup(self, term: str) -> int | None:
        """Id for *term* or None — never assigns."""
        return self._ids.get(term)

    def term(self, i: int) -> str:
        return self._terms[i]

    def __len__(self) -> int:
        return len(self._terms)

    def __contains__(self, term: object) -> bool:
        return term in self._ids

    @property
    def terms(self) -> list[str]:
        """The id-ordered term list (live view — do not mutate)."""
        return self._terms

    def remap_from(self, other_terms: list[str]) -> array:
        """Translation table from another vocab's ids to this vocab's ids.

        ``table[old_id] == self.id(other_terms[old_id])``. Terms unknown
        here are assigned as a side effect, so a cache written against a
        different Vocab instance can be re-based onto this one.
        """
        table = array(U32, (self.id(t) for t in other_terms))
        return table
