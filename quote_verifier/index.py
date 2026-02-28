"""Quote Verifier — Document Index.

Inverted word-position index for fast quote lookup.
Build once per document, query many times.
"""

from collections import defaultdict
from typing import List, Dict, Tuple, Optional

from .config import QuoteVerifierConfig, MatchStrategy
from .normalizer import normalize_with_mapping


class IndexedDocument:
    """A single document's pre-processed data with word-position index."""

    __slots__ = ('name', 'original_text', 'normalized_text',
                 'position_map', 'word_positions',
                 '_collapsed_text', '_collapsed_to_norm')

    def __init__(self, name: str, text: str, config: QuoteVerifierConfig):
        self.name = name
        self.original_text = text
        self.normalized_text, self.position_map, _ = normalize_with_mapping(
            text, config)
        self.word_positions = self._build_word_index()
        self._collapsed_text, self._collapsed_to_norm = self._build_collapsed()

    def _build_word_index(self) -> Dict[str, List[int]]:
        """Map each word to its character start positions in normalized text."""
        index: Dict[str, List[int]] = defaultdict(list)
        text = self.normalized_text
        i = 0
        n = len(text)

        while i < n:
            # Skip whitespace
            while i < n and text[i] == ' ':
                i += 1
            if i >= n:
                break
            # Collect word
            start = i
            while i < n and text[i] != ' ':
                i += 1
            word = text[start:i]
            if word:
                index[word].append(start)

        return dict(index)

    def _build_collapsed(self):
        """Build a space-collapsed version of normalized_text.

        Used as fallback when the primary index misses due to spurious
        spaces in the source (e.g. PDF line-break inside a word).

        Returns (collapsed_text, collapsed_to_norm) where
        collapsed_to_norm[i] is the position in normalized_text.
        """
        collapsed = []
        mapping = []
        for i, ch in enumerate(self.normalized_text):
            if ch != ' ':
                collapsed.append(ch)
                mapping.append(i)
        return ''.join(collapsed), mapping

    def find(self, normalized_quote: str) -> Tuple[int, int, MatchStrategy]:
        """Find quote position using the inverted index.

        Falls back to space-collapsed matching for cases like
        "diphe nyltetrazolium" in source vs "diphenyltetrazolium" in quote.

        Returns (start, end, strategy). (-1, -1, NONE) if not found.
        """
        if not normalized_quote:
            return -1, -1, MatchStrategy.NONE

        result = self._find_exact(normalized_quote)
        if result[0] != -1:
            return result[0], result[1], MatchStrategy.EXACT

        result = self._find_collapsed(normalized_quote)
        if result[0] != -1:
            return result[0], result[1], MatchStrategy.COLLAPSED

        return -1, -1, MatchStrategy.NONE

    def _find_exact(self, normalized_quote: str) -> Tuple[int, int]:
        """Primary lookup via inverted word-position index."""
        space_idx = normalized_quote.find(' ')
        first_word = normalized_quote[:space_idx] if space_idx != -1 else normalized_quote

        candidates = self.word_positions.get(first_word)
        if not candidates:
            return -1, -1

        quote_len = len(normalized_quote)
        text = self.normalized_text
        text_len = len(text)

        for pos in candidates:
            if pos + quote_len <= text_len:
                if text[pos:pos + quote_len] == normalized_quote:
                    return pos, pos + quote_len - 1

        return -1, -1

    def _find_collapsed(self, normalized_quote: str) -> Tuple[int, int]:
        """Fallback: match with all spaces removed from both sides.

        Handles PDF line-break artifacts where source has spurious spaces
        inside words that the quote doesn't.
        """
        collapsed_quote = normalized_quote.replace(' ', '')
        if not collapsed_quote:
            return -1, -1

        idx = self._collapsed_text.find(collapsed_quote)
        if idx == -1:
            return -1, -1

        # Map start and end back to normalized_text positions
        start = self._collapsed_to_norm[idx]
        end = self._collapsed_to_norm[idx + len(collapsed_quote) - 1]
        return start, end


class DocumentIndex:
    """Registry of indexed documents. Build once, query by name."""

    def __init__(
        self,
        documents: Dict[str, str] | None = None,
        config: QuoteVerifierConfig | None = None,
    ):
        self.config = config or QuoteVerifierConfig()
        self.documents: Dict[str, IndexedDocument] = {}

        if documents:
            for name, text in documents.items():
                self.add(name, text)

    def add(self, name: str, text: str) -> IndexedDocument:
        """Index a document. Overwrites if name already exists."""
        doc = IndexedDocument(name, text, self.config)
        self.documents[name] = doc
        return doc

    def get(self, name: str) -> IndexedDocument:
        """Get an indexed document by name. Raises KeyError if not found."""
        if name not in self.documents:
            raise KeyError(f"Document not indexed: {name}")
        return self.documents[name]

    def find_in(self, name: str, normalized_quote: str) -> Tuple[int, int]:
        """Find a normalized quote in a named document. Returns (-1, -1) if not found."""
        return self.get(name).find(normalized_quote)

    def __contains__(self, name: str) -> bool:
        return name in self.documents

    def __len__(self) -> int:
        return len(self.documents)
