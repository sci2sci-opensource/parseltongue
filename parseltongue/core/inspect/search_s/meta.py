"""Metadata index — token, word, line, and document level marks.

Four granularity levels:
    token  — a specific token occurrence at a char position
    word   — all occurrences of a normalized word in this document
    line   — a line number carries marks
    doc    — whole document carries marks

Each mark is a (key, value, weight) triple. The key is a namespace
like "name", "ner:exception", "type". The value is the payload.
The weight is the boost factor for ranking (default 1.0).

MetaIndex collects marks from all four levels for a given query hit,
returning accumulated MetaMarks for ranking/filtering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .stemmer import stem


@dataclass(slots=True)
class MetaMark:
    """A single metadata annotation."""

    key: str  # namespace: "name", "ner:person", "type", ...
    value: str  # payload
    weight: float = 1.0  # boost factor
    text: str = ""  # human-readable description (e.g. "Found document lang.py")


@dataclass
class MetaIndex:
    """Four-level metadata index for a single document.

    Attach marks at any level, query by collecting all marks
    that apply to a given hit (word + line + doc).
    """

    token_meta: dict[int, list[MetaMark]] = field(default_factory=dict)
    word_meta: dict[str, list[MetaMark]] = field(default_factory=dict)
    line_meta: dict[int, list[MetaMark]] = field(default_factory=dict)
    doc_meta: list[MetaMark] = field(default_factory=list)

    # Stemmed word → marks (auto-populated from word_meta)
    _stem_meta: dict[str, list[MetaMark]] = field(default_factory=dict)

    def add_token(self, char_pos: int, key: str, value: str, weight: float = 1.0, text: str = ""):
        """Mark a specific token occurrence."""
        self.token_meta.setdefault(char_pos, []).append(MetaMark(key, value, weight, text))

    def add_word(self, word: str, key: str, value: str, weight: float = 1.0, text: str = ""):
        """Mark all occurrences of a normalized word."""
        mark = MetaMark(key, value, weight, text)
        self.word_meta.setdefault(word, []).append(mark)
        self._stem_meta.setdefault(stem(word), []).append(mark)

    def add_line(self, line_num: int, key: str, value: str, weight: float = 1.0, text: str = ""):
        """Mark a specific line."""
        self.line_meta.setdefault(line_num, []).append(MetaMark(key, value, weight, text))

    def add_doc(self, key: str, value: str, weight: float = 1.0, text: str = ""):
        """Mark the whole document."""
        self.doc_meta.append(MetaMark(key, value, weight, text))

    def collect(self, word: str | None = None, line_num: int | None = None) -> list[MetaMark]:
        """Collect all marks applicable to a hit.

        Resolves up the chain: word → line → doc.
        Returns deduplicated marks from all matching levels.
        """
        marks: list[MetaMark] = []

        if word is not None:
            marks.extend(self.word_meta.get(word, []))
            marks.extend(self._stem_meta.get(stem(word), []))

        if line_num is not None:
            marks.extend(self.line_meta.get(line_num, []))

        marks.extend(self.doc_meta)
        return marks

    def boost(self, word: str | None = None, line_num: int | None = None) -> float:
        """Total boost factor for a hit — product of all applicable weights."""
        marks = self.collect(word, line_num)
        if not marks:
            return 1.0
        result = 1.0
        for m in marks:
            result *= m.weight
        return result

    def matches_query(self, query_tokens: list[str]) -> list[MetaMark]:
        """Check if any meta keys or values match the query tokens.

        Returns marks whose keys or values contain any query token (direct or stemmed).
        Flat list — use matches_query_located for line-aware results.
        """
        return [m for _, m in self.matches_query_located(query_tokens)]

    def matches_query_located(self, query_tokens: list[str]) -> list[tuple[int | None, MetaMark]]:
        """Like matches_query but returns (line_num, mark) pairs.

        line_num is None for doc-level marks, int for line-level marks.
        Word-level marks return None (they apply to all occurrences).
        """
        stemmed_query = {stem(t) for t in query_tokens}
        result: list[tuple[int | None, MetaMark]] = []

        def _matches(mark: MetaMark) -> bool:
            value_tokens = _tokenize_meta_value(mark.value)
            key_tokens = _tokenize_meta_value(mark.key)
            all_stems = {stem(t) for t in value_tokens} | {stem(t) for t in key_tokens}
            return bool(stemmed_query & all_stems)

        # Doc-level: line=None
        for mark in self.doc_meta:
            if _matches(mark):
                result.append((None, mark))

        # Word-level: line=None
        for marks in self.word_meta.values():
            for mark in marks:
                if _matches(mark):
                    result.append((None, mark))

        # Line-level: actual line number
        for line_num, marks in self.line_meta.items():
            for mark in marks:
                if _matches(mark):
                    result.append((line_num, mark))

        return result


def _tokenize_meta_value(value: str) -> list[str]:
    """Split a metadata value into searchable tokens.

    Handles dot-separated names, paths, identifiers:
        "lang.py" → ["lang", "py"]
        "engine.eval-bind" → ["engine", "eval", "bind"]
        "ner:exception" → ["ner", "exception"]
    """
    return [t for t in re.split(r"[.\-_/: ]+", value.lower()) if t]


def index_doc_name(meta: MetaIndex, name: str, weight: float = 10.0):
    """Index a document name as doc-level and word-level meta.

    High default boost — a filename match is almost always the intended target.

    Splits the name into tokens and adds:
    - doc-level mark with full name (full boost)
    - word-level marks for each token (partial boost, for stemmed matching)
    """
    meta.add_doc("name", name, weight, text=f"Found document {name}")
    for token in _tokenize_meta_value(name):
        meta.add_word(token, "name:token", name, weight * 0.5, text=f"Found document {name}")
