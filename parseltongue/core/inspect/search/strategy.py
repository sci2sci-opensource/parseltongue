"""Search strategy — cascade: direct → stemmed → n-gram.

Each strategy level produces a posting set. The cascade tries
levels in order, returning the first non-empty result. Alternatively,
``merge`` runs all levels and combines with decreasing confidence weights.

Strategies:
    direct  — exact normalized word/phrase match via word_to_lines
    stemmed — stem query tokens, match against stem_to_lines
    ngram   — bigram/trigram overlap, ranked by Jaccard similarity

The ``(strategy ...)`` operator in the search system wires into this.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .stemmer import stem

if TYPE_CHECKING:
    from .index import DocumentSearchIndex

# Confidence weights for cascade merge
WEIGHT_DIRECT = 1.0
WEIGHT_STEMMED = 0.7
WEIGHT_NGRAM = 0.4


def _tokenize_query(query: str) -> list[str]:
    """Split a query string into normalized tokens."""
    return query.lower().split()


def search_direct(index: "DocumentSearchIndex", query: str) -> dict:
    """Exact normalized match — word_to_lines intersection."""
    tokens = _tokenize_query(query)
    if not tokens:
        return {}
    result = {}
    for doc_name, sdoc in index.documents.items():
        candidate_lines = sdoc.lines_with_all_words(tokens)
        for line_num in candidate_lines:
            if line_num <= len(sdoc.lines):
                key = (doc_name, line_num)
                result[key] = {
                    "document": doc_name,
                    "line": line_num,
                    "column": 1,
                    "context": sdoc.lines[line_num - 1],
                    "callers": [],
                    "total_callers": 0,
                }
    return result


def search_stemmed(index: "DocumentSearchIndex", query: str) -> dict:
    """Stemmed match — stem query tokens, intersect stem_to_lines."""
    tokens = _tokenize_query(query)
    if not tokens:
        return {}
    result = {}
    for doc_name, sdoc in index.documents.items():
        candidate_lines = sdoc.lines_with_all_stems(tokens)
        for line_num in candidate_lines:
            if line_num <= len(sdoc.lines):
                key = (doc_name, line_num)
                result[key] = {
                    "document": doc_name,
                    "line": line_num,
                    "column": 1,
                    "context": sdoc.lines[line_num - 1],
                    "callers": [],
                    "total_callers": 0,
                }
    return result


def search_ngram(index: "DocumentSearchIndex", query: str) -> dict:
    """N-gram match — bigram/trigram candidate lines, verify substring."""
    tokens = _tokenize_query(query)
    if not tokens:
        return {}

    stemmed_tokens = [stem(t) for t in tokens]
    result = {}

    for doc_name, sdoc in index.documents.items():
        # Get candidate lines from n-gram index using stemmed tokens
        candidates = sdoc.ngram_index.query(stemmed_tokens)
        if not candidates and len(tokens) == 1:
            # Single token — fall back to stem lookup
            candidates = sdoc.lines_with_stem(tokens[0])

        for line_num in candidates:
            if line_num <= len(sdoc.lines):
                key = (doc_name, line_num)
                result[key] = {
                    "document": doc_name,
                    "line": line_num,
                    "column": 1,
                    "context": sdoc.lines[line_num - 1],
                    "callers": [],
                    "total_callers": 0,
                }
    return result


def cascade(index: "DocumentSearchIndex", query: str) -> dict:
    """Try direct → stemmed → n-gram, return first non-empty."""
    result = search_direct(index, query)
    if result:
        return result
    result = search_stemmed(index, query)
    if result:
        return result
    return search_ngram(index, query)


def merge(index: "DocumentSearchIndex", query: str) -> dict:
    """Run all strategies, merge with confidence weights.

    Each posting gets a ``_confidence`` field reflecting which strategy found it.
    Direct matches rank highest.
    """
    direct = search_direct(index, query)
    stemmed = search_stemmed(index, query)
    ngram = search_ngram(index, query)

    merged: dict = {}

    # N-gram first (lowest priority)
    for key, entry in ngram.items():
        entry["_confidence"] = WEIGHT_NGRAM
        merged[key] = entry

    # Stemmed overwrites n-gram
    for key, entry in stemmed.items():
        entry["_confidence"] = WEIGHT_STEMMED
        merged[key] = entry

    # Direct overwrites everything
    for key, entry in direct.items():
        entry["_confidence"] = WEIGHT_DIRECT
        merged[key] = entry

    return merged


# Strategy dispatch table
STRATEGIES = {
    "direct": search_direct,
    "stemmed": search_stemmed,
    "ngram": search_ngram,
    "cascade": cascade,
    "merge": merge,
}
