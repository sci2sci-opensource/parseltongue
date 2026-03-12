"""Searchable — mixin for find/fuzzy over a set of names.

Used by Lens, Hologram, Diagnosis, and anything else that has a ``_names`` set.
"""

from __future__ import annotations

import re


class Searchable:
    """Mixin providing regex ``find`` and ranked ``fuzzy`` search over ``_names``."""

    @property
    def _names(self) -> set[str]:
        raise NotImplementedError

    def find(self, pattern: str, max_results: int = 50) -> list[str]:
        """Search names by regex pattern."""
        rx = re.compile(pattern)
        return sorted(name for name in self._names if rx.search(name))[:max_results]

    def fuzzy(self, query: str, max_results: int = 10) -> list[str]:
        """Find names containing query as substring, ranked by relevance.

        Ranking: exact match (0) > suffix (1) > prefix (2) > substring (3).
        Ties broken by shorter name first.
        """
        query_lower = query.lower()
        scored = []
        for name in self._names:
            name_lower = name.lower()
            if query_lower not in name_lower:
                continue
            if name_lower == query_lower:
                score = 0
            elif name_lower.endswith(query_lower):
                score = 1
            elif name_lower.startswith(query_lower):
                score = 2
            else:
                score = 3
            scored.append((score, len(name), name))
        scored.sort()
        return [name for _, _, name in scored[:max_results]]
