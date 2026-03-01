"""Quote Verifier — Public API.

Re-exports the main classes so users can write:
    from quote_verifier import QuoteVerifier, DocumentIndex
"""

from .config import (
    ConfidenceLevel,
    MatchStrategy,
    NormalizationTransformation,
    Position,
    QuoteVerifierConfig,
)
from .index import DocumentIndex, IndexedDocument
from .verifier import QuoteVerifier
