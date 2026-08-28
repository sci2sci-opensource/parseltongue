"""Array-backed postings for the search engine.

The line-level index is a set of ``(term, document, line)`` triples. Held
as ``dict[str, set[int]]`` per document, every triple was a boxed int in a
set object and every (term, document) pair a dict entry keyed by a
repeated string. Here the same information is a CSR layout over
``array('I')``:

    terms   — sorted term ids (see quote_verifier.vocab.Vocab)
    offsets — offsets[k] .. offsets[k+1] is the run for terms[k]
    values  — the flat run data (line numbers, or doc ids at corpus level)

A :class:`LineSet` is a read-only sorted run of line numbers with the set
operators the query layer uses (``&``, ``|``, ``in``, ``len``, iteration);
:class:`TermLines` is the per-document ``term → LineSet`` mapping view.
"""

from __future__ import annotations

from array import array
from bisect import bisect_left
from collections.abc import Iterable, Iterator, Mapping
from typing import TYPE_CHECKING

from parseltongue.core.quote_verifier.posmap import U32

if TYPE_CHECKING:
    from parseltongue.core.quote_verifier.vocab import Vocab


def _merge_and(a: array, b: array) -> array:
    """Intersection of two sorted arrays, linear merge."""
    out = array(U32)
    i = j = 0
    na, nb = len(a), len(b)
    while i < na and j < nb:
        x, y = a[i], b[j]
        if x == y:
            out.append(x)
            i += 1
            j += 1
        elif x < y:
            i += 1
        else:
            j += 1
    return out


def _merge_or(a: array, b: array) -> array:
    """Union of two sorted arrays, linear merge."""
    out = array(U32)
    i = j = 0
    na, nb = len(a), len(b)
    while i < na and j < nb:
        x, y = a[i], b[j]
        if x == y:
            out.append(x)
            i += 1
            j += 1
        elif x < y:
            out.append(x)
            i += 1
        else:
            out.append(y)
            j += 1
    if i < na:
        out.extend(a[i:])
    if j < nb:
        out.extend(b[j:])
    return out


class LineSet:
    """Immutable, sorted set of line numbers backed by ``array('I')``.

    Behaves like a ``frozenset[int]`` for the operations the engine uses.
    Binary operators accept another LineSet or any iterable of ints.
    """

    __slots__ = ("_a",)

    def __init__(self, sorted_array: array):
        self._a = sorted_array

    @classmethod
    def of(cls, lines: Iterable[int]) -> "LineSet":
        return cls(array(U32, sorted(set(lines))))

    @property
    def data(self) -> array:
        return self._a

    def __len__(self) -> int:
        return len(self._a)

    def __bool__(self) -> bool:
        return len(self._a) > 0

    def __iter__(self) -> Iterator[int]:
        return iter(self._a)

    def __contains__(self, line: object) -> bool:
        if not isinstance(line, int):
            return False
        a = self._a
        k = bisect_left(a, line)
        return k < len(a) and a[k] == line

    def _coerce(self, other: object) -> array | None:
        if isinstance(other, LineSet):
            return other._a
        if isinstance(other, (set, frozenset, list, tuple, array)):
            return array(U32, sorted(set(other)))
        return None

    def __and__(self, other: object) -> "LineSet":
        b = self._coerce(other)
        if b is None:
            return NotImplemented
        return LineSet(_merge_and(self._a, b))

    __rand__ = __and__

    def __or__(self, other: object) -> "LineSet":
        b = self._coerce(other)
        if b is None:
            return NotImplemented
        return LineSet(_merge_or(self._a, b))

    __ror__ = __or__

    def __eq__(self, other: object) -> bool:
        if isinstance(other, LineSet):
            return self._a == other._a
        if isinstance(other, (set, frozenset)):
            return len(other) == len(self._a) and all(x in other for x in self._a)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._a.tobytes())

    def __repr__(self) -> str:
        return f"LineSet({list(self._a)!r})"

    def to_set(self) -> set[int]:
        return set(self._a)


EMPTY = LineSet(array(U32))


class CSR:
    """Sorted-key CSR triple. The building block for every posting table."""

    __slots__ = ("terms", "offsets", "values")

    def __init__(self, terms: array, offsets: array, values: array):
        self.terms = terms
        self.offsets = offsets
        self.values = values

    @classmethod
    def empty(cls) -> "CSR":
        return cls(array(U32), array(U32, [0]), array(U32))

    @classmethod
    def build(cls, runs: Mapping[int, Iterable[int]]) -> "CSR":
        """From ``term_id → iterable of values``; each run is sorted+deduped."""
        terms = array(U32, sorted(runs))
        offsets = array(U32, [0])
        values = array(U32)
        for tid in terms:
            values.extend(sorted(set(runs[tid])))
            offsets.append(len(values))
        return cls(terms, offsets, values)

    @classmethod
    def from_pairs(cls, keys: array, values: array, key_space: int) -> "CSR":
        """From parallel (key, value) arrays — counting sort on the key.

        Keys are ids in ``[0, key_space)``. Values keep their input order
        within a key, so feeding them in ascending order (documents in doc-id
        order, lines in text order) yields sorted runs with no per-run sort.
        Peak memory is a handful of u32 arrays, never a dict of lists.
        """
        counts = array(U32, bytes(4 * key_space))
        for k in keys:
            counts[k] += 1
        terms = array(U32, (k for k in range(key_space) if counts[k]))
        offsets = array(U32, [0])
        # Position of each key's run start in the output.
        starts = array(U32, bytes(4 * key_space))
        pos = 0
        for k in terms:
            starts[k] = pos
            pos += counts[k]
            offsets.append(pos)
        out = array(U32, bytes(4 * len(keys)))
        for k, v in zip(keys, values):
            out[starts[k]] = v
            starts[k] += 1
        return cls(terms, offsets, out)

    def slot(self, tid: int) -> int:
        terms = self.terms
        k = bisect_left(terms, tid)
        if k < len(terms) and terms[k] == tid:
            return k
        return -1

    def run(self, k: int) -> array:
        off = self.offsets
        return self.values[off[k] : off[k + 1]]

    def get(self, tid: int) -> array | None:
        k = self.slot(tid)
        return None if k < 0 else self.run(k)

    def run_len(self, k: int) -> int:
        off = self.offsets
        return off[k + 1] - off[k]

    def __len__(self) -> int:
        return len(self.terms)

    def remapped(self, id_remap: array) -> "CSR":
        """This table with every term id translated through *id_remap*."""
        from parseltongue.core.quote_verifier.index import remap_csr

        t, o, v = remap_csr(self.terms, self.offsets, self.values, id_remap)
        return CSR(t, o, v)

    def to_blobs(self, prefix: str) -> dict[str, bytes]:
        return {
            f"{prefix}.t": self.terms.tobytes(),
            f"{prefix}.o": self.offsets.tobytes(),
            f"{prefix}.v": self.values.tobytes(),
        }

    @classmethod
    def from_blobs(cls, blobs: Mapping[str, bytes | memoryview], prefix: str) -> "CSR":
        t = array(U32)
        t.frombytes(blobs[f"{prefix}.t"])
        o = array(U32)
        o.frombytes(blobs[f"{prefix}.o"])
        v = array(U32)
        v.frombytes(blobs[f"{prefix}.v"])
        return cls(t, o, v)


class TermLines(Mapping[str, LineSet]):
    """``term → LineSet`` view over a CSR, keyed by term string via a Vocab.

    Drop-in for the ``dict[str, set[int]]`` it replaces: ``get``, ``in``,
    ``[]``, ``items()``, ``keys()``, ``len()``. Id-keyed access
    (:meth:`by_id`) is what the corpus-level code uses.
    """

    __slots__ = ("_csr", "_vocab")

    def __init__(self, csr: CSR, vocab: "Vocab"):
        self._csr = csr
        self._vocab = vocab

    @property
    def csr(self) -> CSR:
        return self._csr

    def by_id(self, tid: int) -> LineSet | None:
        run = self._csr.get(tid)
        return None if run is None else LineSet(run)

    def __getitem__(self, term: str) -> LineSet:
        tid = self._vocab.lookup(term)
        if tid is None:
            raise KeyError(term)
        ls = self.by_id(tid)
        if ls is None:
            raise KeyError(term)
        return ls

    def get(self, term: str, default=None):
        tid = self._vocab.lookup(term)
        if tid is None:
            return default
        ls = self.by_id(tid)
        return default if ls is None else ls

    def __contains__(self, term: object) -> bool:
        if not isinstance(term, str):
            return False
        tid = self._vocab.lookup(term)
        return tid is not None and self._csr.slot(tid) >= 0

    def __iter__(self) -> Iterator[str]:
        vocab = self._vocab
        for tid in self._csr.terms:
            yield vocab.term(tid)

    def __len__(self) -> int:
        return len(self._csr)

    def items(self):  # noqa: D102 — Mapping.items() returning a generator
        vocab = self._vocab
        csr = self._csr
        for k, tid in enumerate(csr.terms):
            yield vocab.term(tid), LineSet(csr.run(k))

    def ids(self) -> array:
        return self._csr.terms


class TermCounts(Mapping[str, int]):
    """``term → count`` over an id-indexed ``array('I')`` (document frequency)."""

    __slots__ = ("_counts", "_vocab")

    def __init__(self, counts: array, vocab: "Vocab"):
        self._counts = counts
        self._vocab = vocab

    def by_id(self, tid: int) -> int:
        c = self._counts
        return c[tid] if tid < len(c) else 0

    def __getitem__(self, term: str) -> int:
        tid = self._vocab.lookup(term)
        if tid is None or tid >= len(self._counts) or self._counts[tid] == 0:
            raise KeyError(term)
        return self._counts[tid]

    def get(self, term: str, default=0):
        tid = self._vocab.lookup(term)
        if tid is None:
            return default
        c = self.by_id(tid)
        return c if c else default

    def __iter__(self) -> Iterator[str]:
        vocab = self._vocab
        for tid, c in enumerate(self._counts):
            if c:
                yield vocab.term(tid)

    def __len__(self) -> int:
        return sum(1 for c in self._counts if c)

    def __contains__(self, term: object) -> bool:
        return isinstance(term, str) and self.get(term, 0) > 0
