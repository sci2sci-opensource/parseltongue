"""RunMap — a monotone integer sequence stored as runs.

Position maps (normalized char index → original char index, collapsed
index → normalized index) are non-decreasing and advance by exactly one
almost everywhere: normalization only breaks the +1 rhythm where it drops
or merges characters. Storing one Python ``int`` per character costs
~36 bytes each; storing only the run starts costs two 32-bit words per
*edit*, which for source text is one to two orders of magnitude fewer.

``seq[i]`` for ``i`` inside run ``k`` is ``values[k] + (i - starts[k])``.
Lookup is a bisect on ``starts``.
"""

from __future__ import annotations

from array import array
from bisect import bisect_right
from collections.abc import Iterable, Iterator, Sequence
from typing import overload

U32 = "I" if array("I").itemsize == 4 else "L"


class RunMap(Sequence[int]):
    """Read-only sequence of non-negative ints, run-length encoded."""

    __slots__ = ("_starts", "_values", "_len")

    def __init__(self, starts: array, values: array, length: int):
        self._starts = starts
        self._values = values
        self._len = length

    # ── construction ──

    @classmethod
    def from_seq(cls, seq: Iterable[int]) -> "RunMap":
        starts = array(U32)
        values = array(U32)
        prev = -2
        n = 0
        for i, v in enumerate(seq):
            if v != prev + 1:
                starts.append(i)
                values.append(v)
            prev = v
            n = i + 1
        return cls(starts, values, n)

    @classmethod
    def identity(cls, length: int) -> "RunMap":
        if length == 0:
            return cls(array(U32), array(U32), 0)
        return cls(array(U32, [0]), array(U32, [0]), length)

    # ── sequence protocol ──

    def __len__(self) -> int:
        return self._len

    @overload
    def __getitem__(self, i: int) -> int: ...
    @overload
    def __getitem__(self, i: slice) -> list[int]: ...

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self[j] for j in range(*i.indices(self._len))]
        n = self._len
        if i < 0:
            i += n
        if i < 0 or i >= n:
            raise IndexError("RunMap index out of range")
        k = bisect_right(self._starts, i) - 1
        return self._values[k] + (i - self._starts[k])

    def __iter__(self) -> Iterator[int]:
        starts, values, n = self._starts, self._values, self._len
        for k in range(len(starts)):
            end = starts[k + 1] if k + 1 < len(starts) else n
            base = values[k] - starts[k]
            for i in range(starts[k], end):
                yield base + i

    def __eq__(self, other: object) -> bool:
        if isinstance(other, RunMap):
            return self._len == other._len and self._starts == other._starts and self._values == other._values
        if isinstance(other, Sequence):
            return len(other) == self._len and all(a == b for a, b in zip(self, other))
        return NotImplemented

    def __hash__(self) -> int:  # Sequence sets __hash__ = None; keep RunMap hashable by identity
        return id(self)

    def __repr__(self) -> str:
        return f"RunMap(len={self._len}, runs={len(self._starts)})"

    # ── persistence ──

    @property
    def runs(self) -> int:
        return len(self._starts)

    def to_blobs(self) -> tuple[bytes, bytes]:
        return self._starts.tobytes(), self._values.tobytes()

    @classmethod
    def from_blobs(cls, starts: bytes | memoryview, values: bytes | memoryview, length: int) -> "RunMap":
        s = array(U32)
        s.frombytes(starts)
        v = array(U32)
        v.frombytes(values)
        return cls(s, v, length)
