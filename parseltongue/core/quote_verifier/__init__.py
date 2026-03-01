"""Quote Verifier — Public API.

Re-exports the main classes so users can write:
    from quote_verifier import QuoteVerifier, DocumentIndex
"""

from .config import (
    ConfidenceLevel as ConfidenceLevel,
)
from .config import (
    MatchStrategy as MatchStrategy,
)
from .config import (
    NormalizationTransformation as NormalizationTransformation,
)
from .config import (
    Position as Position,
)
from .config import (
    QuoteVerifierConfig as QuoteVerifierConfig,
)
from .index import DocumentIndex as DocumentIndex
from .index import IndexedDocument as IndexedDocument
from .verifier import QuoteVerifier as QuoteVerifier
