"""Search infrastructure — line-level indices, stemming, n-grams, strategies.

Builds on top of quote_verifier's IndexedDocument / DocumentIndex.
"""

from .document import SearchDocument
from .index import DocumentSearchIndex
from .ngrams import NGramIndex
from .stemmer import stem, stem_tokens
from .strategy import STRATEGIES, cascade, merge, search_direct, search_ngram, search_stemmed

__all__ = [
    "DocumentSearchIndex",
    "NGramIndex",
    "SearchDocument",
    "STRATEGIES",
    "cascade",
    "merge",
    "search_direct",
    "search_ngram",
    "search_stemmed",
    "stem",
    "stem_tokens",
]
