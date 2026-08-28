"""Search infrastructure — line-level indices, stemming, phrases, metadata, synonyms, strategies.

Builds on top of quote_verifier's IndexedDocument / DocumentIndex.
"""

from .annotators import (
    DEFAULT_ANNOTATORS,
    AnnotationStrategy,
    DefinitionAnnotator,
    ExceptionHandlingAnnotator,
    ImportAnnotator,
)
from .document import SearchDocument
from .index import DocumentSearchIndex
from .meta import MetaIndex, MetaMark, index_doc_name
from .postings import LineSet, TermLines
from .stemmer import stem, stem_tokens
from .strategy import (
    STRATEGIES,
    cascade,
    merge,
    search_direct,
    search_meta,
    search_ngram,
    search_rrf,
    search_stemmed,
)
from .synonyms import DEFAULT_SYNONYMS, ExpansionScope, SynonymEntry, SynonymIndex

__all__ = [
    "AnnotationStrategy",
    "DEFAULT_ANNOTATORS",
    "DEFAULT_SYNONYMS",
    "DefinitionAnnotator",
    "DocumentSearchIndex",
    "ExceptionHandlingAnnotator",
    "ExpansionScope",
    "ImportAnnotator",
    "LineSet",
    "MetaIndex",
    "MetaMark",
    "SearchDocument",
    "TermLines",
    "STRATEGIES",
    "SynonymEntry",
    "SynonymIndex",
    "cascade",
    "index_doc_name",
    "merge",
    "search_direct",
    "search_meta",
    "search_ngram",
    "search_rrf",
    "search_stemmed",
    "stem",
    "stem_tokens",
]
