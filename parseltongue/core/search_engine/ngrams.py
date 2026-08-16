"""N-gram index over token sequences.

Builds bigram and trigram indices from a list of (line_number, tokens) pairs.
Queries return candidate line sets via set intersection of n-gram postings.
"""

from __future__ import annotations

from collections import defaultdict


class NGramIndex:
    """Bigram and trigram index over per-line token sequences.

    Build from line_tokens: list of (line_number, [token, ...]).
    Query with a token sequence — returns candidate line numbers.
    """

    def __init__(self):
        self.bigrams: dict[tuple[str, str], set[int]] = defaultdict(set)
        self.trigrams: dict[tuple[str, str, str], set[int]] = defaultdict(set)

    def build(self, line_tokens: list[tuple[int, list[str]]]):
        """Index all lines. Each entry is (1-based line number, tokens)."""
        for line_num, tokens in line_tokens:
            for i in range(len(tokens) - 1):
                self.bigrams[(tokens[i], tokens[i + 1])].add(line_num)
            for i in range(len(tokens) - 2):
                self.trigrams[(tokens[i], tokens[i + 1], tokens[i + 2])].add(line_num)

    def query_bigrams(self, tokens: list[str]) -> set[int] | None:
        """Intersect bigram postings for a token sequence.

        Returns None if no bigrams can be formed (single token or empty).
        """
        if len(tokens) < 2:
            return None
        result: set[int] | None = None
        for i in range(len(tokens) - 1):
            key = (tokens[i], tokens[i + 1])
            posting = self.bigrams.get(key)
            if posting is None:
                return set()
            result = posting if result is None else result & posting
        return result

    def query_trigrams(self, tokens: list[str]) -> set[int] | None:
        """Intersect trigram postings for a token sequence.

        Returns None if no trigrams can be formed (< 3 tokens).
        """
        if len(tokens) < 3:
            return None
        result: set[int] | None = None
        for i in range(len(tokens) - 2):
            key = (tokens[i], tokens[i + 1], tokens[i + 2])
            posting = self.trigrams.get(key)
            if posting is None:
                return set()
            result = posting if result is None else result & posting
        return result

    def query(self, tokens: list[str]) -> set[int]:
        """Best-effort candidate lines: try trigrams first, fall back to bigrams.

        For single tokens, returns empty set (caller should use word_to_lines).
        """
        tri = self.query_trigrams(tokens)
        if tri is not None:
            return tri
        bi = self.query_bigrams(tokens)
        if bi is not None:
            return bi
        return set()
