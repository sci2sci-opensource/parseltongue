"""BenchSystem — base class and protocols for bench subsystems.

BenchSubsystem protocol: a Rewriter with a PostingMorphism and a tag.
Each subsystem (Lens, Evaluation, Hologram search systems) implements
BenchSubsystem so the Search layer can dispatch tagged forms back to
postings by head symbol.

OpsMorphism protocol: key extraction for fast pointer/vectorized ops.
Subsystems implement this to tell ops how to identify their forms.
OpsView: lazy batch view over tagged forms — pointer and vectorized regimes.

BenchSystem: base class for frozen/live bench systems with scope registration.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from typing import TYPE_CHECKING, Protocol

from parseltongue.core.atoms import Symbol
from parseltongue.core.lang import Sentence

if TYPE_CHECKING:
    from parseltongue.core.system import System


# Posting dict: {(doc_name, line_num): {document, line, column, context, callers, total_callers}}
Posting = dict[tuple[str, int], dict]

# DocSet: Posting with line_num=0 — doc-level entries from match_docs / 1-arg (in)
DocSet = Posting


class PostingMorphism(Protocol):
    """Bidirectional map between posting dicts and tagged forms.

    transform:  posting → tagged forms (for pltg-native output)
    inverse:    tagged forms → posting (for display/ranking)
    """

    def transform(self, posting: Posting) -> list: ...
    def inverse(self, forms: list) -> Posting: ...


class OpsMorphism(Protocol):
    """Key extraction for fast operations over tagged forms.

    Subsystems implement this to define identity for their forms.
    Ops never touches the body — just the key. The subsystem decides
    what constitutes identity (name, (doc, line), etc.).

    Two regimes use this:
    - Pointer: set ops (and/not/or) on key sets, bodies untouched.
    - Vectorized: count/limit/future aggregation on the list itself.
    """

    def key(self, form: Sequence) -> Hashable:
        """Extract identity key from a single tagged form."""
        ...


class OpsView:
    """Lazy indexed view over tagged forms for fast batch operations.

    Pointer regime: extract keys, do set ops, reconstruct from winners.
    Bodies are never copied or inspected — only indices and keys.

    Vectorized regime: len/slice on the underlying list.
    Future: columnar decomposition for numeric aggregation.
    """

    __slots__ = ("forms", "_key_fn", "_keys", "_key_set")

    def __init__(self, forms: list, key_fn: Callable[[Sequence], Hashable]):
        self.forms = forms
        self._key_fn = key_fn
        self._keys: list[Hashable] | None = None
        self._key_set: set[Hashable] | None = None

    @property
    def keys(self) -> list[Hashable]:
        if self._keys is None:
            self._keys = [self._key_fn(f) for f in self.forms]
        return self._keys

    def key_set(self) -> set[Hashable]:
        if self._key_set is None:
            self._key_set = set(self.keys)
        return self._key_set

    # ── Pointer regime: set operations ──

    def intersect(self, other: OpsView) -> list:
        """AND: forms from self whose key appears in other."""
        keep = other.key_set()
        return [f for f, k in zip(self.forms, self.keys) if k in keep]

    def difference(self, other: OpsView) -> list:
        """NOT: forms from self whose key does NOT appear in other."""
        exclude = other.key_set()
        return [f for f, k in zip(self.forms, self.keys) if k not in exclude]

    def union(self, other: OpsView) -> list:
        """OR: all from self, plus forms from other whose key is new."""
        seen = self.key_set()
        return self.forms + [f for f, k in zip(other.forms, other.keys) if k not in seen]

    # ── Vectorized regime ──

    def __len__(self) -> int:
        return len(self.forms)

    def limit(self, n: int) -> list:
        return self.forms[:n]


class BenchSubsystem(Protocol):
    """A bench subsystem: evaluates expressions and maps results to/from postings.

    tag:               head Symbol that identifies this subsystem's forms (ln, dx, hn, sr)
    posting_morphism:  bidirectional map between posting dicts and tagged forms
    evaluate:          Rewriter — evaluates s-expressions
    """

    tag: Symbol
    posting_morphism: PostingMorphism

    @property
    def data_tags(self) -> list[Symbol]:
        """All Symbol tags that appear as data markers in this subsystem's forms.

        Includes the head tag and any sub-tags (e.g. ln-ev for evidence sublists).
        Collected on scope registration so the parent engine can self-quote them.
        """
        return [self.tag]

    def evaluate(self, expr: Sentence, local_env: dict | None = None) -> Sentence: ...

    @staticmethod
    def matches_tag(head: Symbol, tag: Symbol) -> bool:
        """Check if head symbol matches tag, accounting for canonical namespacing.

        Matches both bare (ln) and canonical (specialized_ops.lens.ln) forms.
        """
        return head == tag or str(head).endswith("." + str(tag))


class BenchSystem:
    """Base for bench systems. Provides scope registration."""

    system: System

    def register_scope(self, name: str, scope_system):
        """Register a scope system as a callable in engine env.

        Calls scope_system.evaluate(expr) which returns raw pltg results
        (posting sets, scalars, lists — whatever the system produces).
        """

        def _scope_fn(_name, *args):
            result = None
            for arg in args:
                if isinstance(arg, (list, tuple)):
                    result = scope_system.evaluate(arg)
                else:
                    result = arg
            return result

        self.system.engine.env[Symbol(name)] = _scope_fn

        # Data tags from scope results must be self-quoting in the engine.
        for tag in getattr(scope_system, "data_tags", [getattr(scope_system, "tag", None)]):
            if tag is not None and tag not in self.system.engine.env:
                self.system.engine.env[tag] = tag
