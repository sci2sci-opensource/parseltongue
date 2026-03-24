"""Synonym index — query expansion with scoped application.

Three expansion scopes:
    universal  — expanded tokens search content + meta
    documents  — expanded tokens search content indices only
    meta       — expanded tokens search meta indices only

Each synonym group is tagged with a scope. expand() filters by scope,
so strategies can request only the expansions relevant to their path.

Synonym groups are bidirectional within their scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .stemmer import stem


class ExpansionScope(Enum):
    """Where synonym expansion applies."""

    UNIVERSAL = "universal"  # content + meta
    DOCUMENTS = "documents"  # content only (word_to_lines, stem_to_lines, ngrams)
    META = "meta"  # meta indices only + direct meta boost


@dataclass(slots=True)
class SynonymEntry:
    """A synonym with relevance weight and expansion scope."""

    term: str
    weight: float = 1.0
    scope: ExpansionScope = ExpansionScope.UNIVERSAL


class SynonymIndex:
    """Bidirectional synonym expansion with scoped filtering.

    expand("exception", scope=UNIVERSAL) → all universal synonyms
    expand("def", scope=META) → only meta-scoped synonyms
    expand("error") → all scopes (no filter)
    """

    def __init__(self):
        self._lookup: dict[str, list[SynonymEntry]] = {}

    def add_group(
        self,
        terms: list[str | tuple[str, float]],
        scope: ExpansionScope = ExpansionScope.UNIVERSAL,
    ):
        """Add a synonym group. All terms expand to each other within scope."""
        entries = []
        for t in terms:
            if isinstance(t, tuple):
                entries.append(SynonymEntry(t[0].lower(), t[1], scope))
            else:
                entries.append(SynonymEntry(t.lower(), 1.0, scope))

        for entry in entries:
            if entry.term not in self._lookup:
                self._lookup[entry.term] = []
            for other in entries:
                if other.term != entry.term:
                    self._lookup[entry.term].append(other)

    def expand(
        self,
        term: str,
        scope: ExpansionScope | None = None,
    ) -> list[SynonymEntry]:
        """Expand a term to synonyms, optionally filtered by scope.

        scope=None → all scopes.
        scope=UNIVERSAL → universal entries only.
        scope=DOCUMENTS → universal + documents entries.
        scope=META → universal + meta entries.

        The term itself is always first with weight 1.0.
        """
        term_lower = term.lower()
        result = [SynonymEntry(term_lower, 1.0, ExpansionScope.UNIVERSAL)]
        seen = {term_lower}

        # Try exact match first, then stemmed form as fallback
        candidates = self._lookup.get(term_lower, [])
        if not candidates:
            candidates = self._lookup.get(stem(term_lower), [])

        for entry in candidates:
            if entry.term in seen:
                continue
            if scope is not None and not _scope_matches(entry.scope, scope):
                continue
            seen.add(entry.term)
            result.append(entry)

        result.sort(key=lambda e: -e.weight)
        return result

    def expand_tokens(
        self,
        tokens: list[str],
        scope: ExpansionScope | None = None,
    ) -> list[list[SynonymEntry]]:
        """Expand each token independently, filtered by scope."""
        return [self.expand(t, scope) for t in tokens]

    def expand_flat(
        self,
        tokens: list[str],
        scope: ExpansionScope | None = None,
    ) -> list[SynonymEntry]:
        """Expand all tokens, flatten, deduplicated. Keeps highest weight per term."""
        best: dict[str, SynonymEntry] = {}
        for t in tokens:
            for entry in self.expand(t, scope):
                if entry.term not in best or entry.weight > best[entry.term].weight:
                    best[entry.term] = entry
        result = list(best.values())
        result.sort(key=lambda e: -e.weight)
        return result


def _scope_matches(entry_scope: ExpansionScope, query_scope: ExpansionScope) -> bool:
    """Check if an entry's scope is compatible with the requested scope.

    UNIVERSAL entries match everything.
    DOCUMENTS entries match DOCUMENTS and UNIVERSAL queries.
    META entries match META and UNIVERSAL queries.
    """
    if entry_scope == ExpansionScope.UNIVERSAL:
        return True
    if query_scope == ExpansionScope.UNIVERSAL:
        return True
    return entry_scope == query_scope


def build_default_synonyms() -> SynonymIndex:
    """Built-in synonym groups for code search."""
    idx = SynonymIndex()
    U = ExpansionScope.UNIVERSAL
    M = ExpansionScope.META
    D = ExpansionScope.DOCUMENTS

    # Exception handling — universal: content "raise" and meta "exception:raise" both relevant
    idx.add_group(
        [
            ("exception", 1.0),
            ("error", 0.9),
            ("raise", 0.8),
            ("throw", 0.8),
            ("try", 0.7),
            ("except", 0.8),
            ("catch", 0.8),
            ("finally", 0.6),
            ("traceback", 0.7),
        ],
        scope=U,
    )

    # Definitions — meta only: "def" in content is a keyword, shouldn't expand to "definition"
    idx.add_group(
        [
            ("definition", 1.0),
            ("def", 0.9),
            ("function", 0.9),
            ("method", 0.8),
            ("class", 0.7),
            ("declare", 0.7),
        ],
        scope=M,
    )

    # Imports — universal
    idx.add_group(
        [
            ("import", 1.0),
            ("require", 0.8),
            ("include", 0.8),
            ("dependency", 0.7),
        ],
        scope=U,
    )

    # Return / output — documents only
    idx.add_group(
        [
            ("return", 1.0),
            ("yield", 0.8),
            ("output", 0.7),
            ("result", 0.7),
        ],
        scope=D,
    )

    # Testing — universal
    idx.add_group(
        [
            ("test", 1.0),
            ("assert", 0.9),
            ("expect", 0.8),
            ("verify", 0.8),
            ("check", 0.7),
            ("mock", 0.7),
        ],
        scope=U,
    )

    # Iteration — documents only (content keywords)
    idx.add_group(
        [
            ("loop", 1.0),
            ("iterate", 0.9),
            ("for", 0.8),
            ("while", 0.8),
            ("each", 0.7),
        ],
        scope=D,
    )

    # Logging — universal
    idx.add_group(
        [
            ("log", 1.0),
            ("debug", 0.8),
            ("print", 0.7),
            ("trace", 0.7),
            ("warn", 0.8),
            ("info", 0.7),
        ],
        scope=U,
    )

    # Conditional — documents only
    idx.add_group(
        [
            ("condition", 1.0),
            ("if", 0.9),
            ("else", 0.8),
            ("branch", 0.7),
        ],
        scope=D,
    )

    return idx


# Singleton default index
DEFAULT_SYNONYMS = build_default_synonyms()
