"""BenchSystem — base class and protocols for bench subsystems.

BenchSubsystem protocol: a Rewriter with a PostingMorphism and a tag.
Each subsystem (Lens, Evaluation, Hologram search systems) implements
BenchSubsystem so the Search layer can dispatch tagged forms back to
postings by head symbol.

BenchSystem: base class for frozen/live bench systems with scope registration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from parseltongue.core.atoms import Symbol
from parseltongue.core.lang import Sentence

if TYPE_CHECKING:
    from parseltongue.core.system import System


# Posting dict: {(doc_name, line_num): {document, line, column, context, callers, total_callers}}
Posting = dict[tuple[str, int], dict]


class PostingMorphism(Protocol):
    """Bidirectional map between posting dicts and tagged forms.

    transform:  posting → tagged forms (for pltg-native output)
    inverse:    tagged forms → posting (for display/ranking)
    """

    def transform(self, posting: Posting) -> list: ...
    def inverse(self, forms: list) -> Posting: ...


class BenchSubsystem(Protocol):
    """A bench subsystem: evaluates expressions and maps results to/from postings.

    tag:               head Symbol that identifies this subsystem's forms (ln, dx, hn, sr)
    posting_morphism:  bidirectional map between posting dicts and tagged forms
    evaluate:          Rewriter — evaluates s-expressions
    """

    tag: Symbol
    posting_morphism: PostingMorphism

    def evaluate(self, expr: Sentence, local_env: dict | None = None) -> Sentence: ...


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
