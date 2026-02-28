"""Quote Verifier — Public API.

Re-exports the main classes so users can write:
    from quote_verifier import QuoteVerifier, DocumentIndex
"""

from .config import QuoteVerifierConfig, ConfidenceLevel, MatchStrategy, NormalizationTransformation, Position
from .verifier import QuoteVerifier
from .index import DocumentIndex, IndexedDocument
