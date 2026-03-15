"""SearchDocument — line-level search index wrapping IndexedDocument.

Adds what IndexedDocument doesn't have:
- Pre-split lines (computed once)
- word → line numbers mapping (from existing word_positions + position_map)
- Stemmed word → line numbers mapping
- N-gram index (bigrams, trigrams)

All built from IndexedDocument's already-normalized text. No re-normalization.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from .ngrams import NGramIndex
from .stemmer import stem

if TYPE_CHECKING:
    from parseltongue.core.quote_verifier.index import IndexedDocument


class SearchDocument:
    """Line-level search index for a single document.

    Wraps an IndexedDocument and adds line-oriented indices
    for fast lookup by word, stemmed word, and n-gram.
    """

    __slots__ = (
        "name",
        "doc",
        "lines",
        "line_ranges",
        "word_to_lines",
        "stem_to_lines",
        "ngram_index",
        "_line_tokens",
    )

    def __init__(self, doc: "IndexedDocument"):
        self.name = doc.name
        self.doc = doc
        self.lines: list[str] = doc.original_text.splitlines()
        self.word_to_lines: dict[str, set[int]] = defaultdict(set)
        self.stem_to_lines: dict[str, set[int]] = defaultdict(set)
        self._line_tokens: list[tuple[int, list[str]]] = []

        self._build_line_indices()

        self.ngram_index = NGramIndex()
        self.ngram_index.build(self._line_tokens)

    def _build_line_indices(self):
        """Build word→lines and stem→lines from normalized text + position_map."""
        doc = self.doc
        norm_text = doc.normalized_text
        pos_map = doc.position_map
        orig_text = doc.original_text

        # Pre-compute line start offsets in original text.
        line_starts = [0]
        for i, ch in enumerate(orig_text):
            if ch == "\n":
                line_starts.append(i + 1)

        # Cache (start_char, end_char) per line — used by enrich for quote overlap.
        # line_ranges[0] = line 1's range (0-indexed list, 1-based lines).
        text_len = len(orig_text)
        self.line_ranges: list[tuple[int, int]] = []
        for idx in range(len(line_starts)):
            start = line_starts[idx]
            end = (line_starts[idx + 1] - 2) if idx + 1 < len(line_starts) else text_len - 1
            self.line_ranges.append((start, max(start, end)))

        def _char_to_line(orig_pos: int) -> int:
            # Binary search for line number
            lo, hi = 0, len(line_starts) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if line_starts[mid] <= orig_pos:
                    lo = mid
                else:
                    hi = mid - 1
            return lo + 1  # 1-based

        # Walk normalized text, extract words, map each to original line
        per_line_tokens: dict[int, list[str]] = defaultdict(list)
        i = 0
        n = len(norm_text)
        while i < n:
            while i < n and norm_text[i] == " ":
                i += 1
            if i >= n:
                break
            start = i
            while i < n and norm_text[i] != " ":
                i += 1
            word = norm_text[start:i]
            if not word:
                continue

            # Map back to original position → line number
            orig_pos = pos_map[start] if start < len(pos_map) else 0
            line_num = _char_to_line(orig_pos)

            self.word_to_lines[word].add(line_num)

            stemmed = stem(word)
            self.stem_to_lines[stemmed].add(line_num)

            per_line_tokens[line_num].append(word)

        # Build line_tokens for n-gram index
        self._line_tokens = [(ln, tokens) for ln, tokens in sorted(per_line_tokens.items())]

    def lines_with_word(self, word: str) -> set[int]:
        """Line numbers (1-based) containing this normalized word."""
        return self.word_to_lines.get(word, set())

    def lines_with_stem(self, word: str) -> set[int]:
        """Line numbers containing any word that stems to the same root."""
        return self.stem_to_lines.get(stem(word), set())

    def lines_with_all_words(self, words: list[str]) -> set[int]:
        """Line numbers containing ALL given words (intersection)."""
        if not words:
            return set()
        result = self.lines_with_word(words[0])
        for w in words[1:]:
            result = result & self.lines_with_word(w)
            if not result:
                break
        return result

    def lines_with_all_stems(self, words: list[str]) -> set[int]:
        """Line numbers containing stems of ALL given words."""
        if not words:
            return set()
        result = self.lines_with_stem(words[0])
        for w in words[1:]:
            result = result & self.lines_with_stem(w)
            if not result:
                break
        return result
