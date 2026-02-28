"""Quote Verifier — Main Verifier Class.

Always uses the inverted index internally. Two flavors:
  - verify_quote / verify_quotes: pass raw text (auto-indexed by hash)
  - verify_indexed / verify_indexed_quotes: pass document name (pre-indexed)
"""

import re
import hashlib
from typing import List, Dict, Set, Optional

from .config import (
    QuoteVerifierConfig, ConfidenceLevel, MatchStrategy,
    NormalizationTransformation, Position,
)
from .normalizer import normalize_with_mapping
from .index import DocumentIndex, IndexedDocument


class QuoteVerifier:
    """Verify if quotes appear in source documents using an inverted index."""

    def __init__(
        self,
        case_sensitive: bool = False,
        ignore_punctuation: bool = True,
        normalize_lists: bool = True,
        normalize_hyphenation: bool = True,
        remove_stopwords: bool = False,
        stopwords: Optional[Set[str]] = None,
        confidence_threshold: float = 0.7,
        config: Optional[QuoteVerifierConfig] = None,
    ):
        if config is not None:
            self.config = config
        else:
            self.config = QuoteVerifierConfig.create_with_overrides(
                case_sensitive=case_sensitive,
                ignore_punctuation=ignore_punctuation,
                normalize_lists=normalize_lists,
                normalize_hyphenation=normalize_hyphenation,
                remove_stopwords=remove_stopwords,
                confidence_threshold=confidence_threshold,
                custom_stopwords=stopwords if stopwords is not None else set(),
            )

        self.index = DocumentIndex(config=self.config)

        # Convenience properties for backward compat
        self.case_sensitive = self.config.case_sensitive
        self.ignore_punctuation = self.config.ignore_punctuation
        self.normalize_lists = self.config.normalize_lists
        self.normalize_hyphenation = self.config.normalize_hyphenation
        self.remove_stopwords = self.config.remove_stopwords
        self.confidence_threshold = self.config.confidence_threshold
        self.stopwords = self.config.stopwords
        self.DEFAULT_STOPWORDS = self.config.default_stopwords
        self.DANGEROUS_STOPWORDS = self.config.dangerous_stopwords

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def build_index(self, documents: Dict[str, str]) -> DocumentIndex:
        """Build an index from a name→text map and attach it."""
        self.index = DocumentIndex(documents, self.config)
        return self.index

    def set_index(self, index: DocumentIndex):
        """Attach a pre-built index."""
        self.index = index

    # ------------------------------------------------------------------
    # Backward-compat normalization access
    # ------------------------------------------------------------------

    def normalize_with_mapping(self, text: str):
        """Normalize text (delegates to normalizer module)."""
        return normalize_with_mapping(text, self.config)

    # ------------------------------------------------------------------
    # By-text verification (auto-indexes via hash)
    # ------------------------------------------------------------------

    def verify_quote(self, document_text: str, quote: str,
                     context_length: int = 40) -> Dict:
        """Verify a quote against raw document text.

        Auto-indexes the document by its content hash if not already indexed.
        """
        doc = self._ensure_indexed_text(document_text)
        return self._verify_from_indexed(doc, quote, context_length)

    def verify_quotes(self, document_text: str, quotes: List[str]) -> List[Dict]:
        """Verify multiple quotes against raw document text."""
        doc = self._ensure_indexed_text(document_text)
        return [self._verify_from_indexed(doc, q) for q in quotes]

    # ------------------------------------------------------------------
    # By-name verification (pre-indexed)
    # ------------------------------------------------------------------

    def verify_indexed(self, doc_name: str, quote: str,
                       context_length: int = 40) -> Dict:
        """Verify a quote against a pre-indexed document by name."""
        doc = self.index.get(doc_name)
        return self._verify_from_indexed(doc, quote, context_length)

    def verify_indexed_quotes(self, doc_name: str,
                              quotes: List[str]) -> List[Dict]:
        """Verify multiple quotes against a pre-indexed document by name."""
        doc = self.index.get(doc_name)
        return [self._verify_from_indexed(doc, q) for q in quotes]

    # ------------------------------------------------------------------
    # Internal: shared verification logic
    # ------------------------------------------------------------------

    def _ensure_indexed_text(self, text: str) -> IndexedDocument:
        """Get or create an IndexedDocument for raw text, keyed by hash."""
        key = hashlib.sha256(text.encode()).hexdigest()[:16]
        if key not in self.index:
            self.index.add(key, text)
        return self.index.get(key)

    def _verify_from_indexed(self, doc: IndexedDocument, quote: str,
                             context_length: int = 40) -> Dict:
        """Core verification against an IndexedDocument."""
        # Pre-validate
        result, ok = self._pre_validate(doc.original_text, quote)
        if not ok:
            return result

        normalized_quote, _, _ = normalize_with_mapping(quote, self.config)
        position_info, confidence_info = self._find_quote_position(
            doc, quote, normalized_quote)

        verified = (
            position_info["original"] is not None
            and confidence_info["score"] >= self.config.confidence_threshold
        )

        original_position = (position_info["original"].start
                             if position_info["original"] else -1)
        normalized_position = (position_info["normalized"].start
                               if position_info["normalized"] else -1)

        context = None
        if position_info["original"]:
            context = self._get_context(
                doc.original_text,
                position_info["original"].start,
                position_info["original"].end,
                context_length,
            )

        result = {
            "quote": quote,
            "verified": verified,
            "original_position": original_position,
            "normalized_position": normalized_position,
            "length": (len(normalized_quote.split())
                       if normalized_quote.strip()
                       else len(quote.split())),
        }

        if position_info["original"]:
            result["positions"] = {
                "original": {
                    "start": position_info["original"].start,
                    "end": position_info["original"].end,
                },
                "normalized": {
                    "start": position_info["normalized"].start,
                    "end": position_info["normalized"].end,
                },
            }

        result["confidence"] = {
            "score": confidence_info["score"],
            "level": confidence_info["level"],
        }

        if confidence_info["transformations"]:
            result["transformations"] = [
                {"type": t.type, "description": t.description, "penalty": t.penalty}
                for t in confidence_info["transformations"]
            ]

        if context:
            result["context"] = context

        if not verified:
            if original_position != -1:
                result["reason"] = "Below confidence threshold"
            else:
                result["reason"] = "Not found in document"

        return result

    def _find_quote_position(self, doc: IndexedDocument, quote: str,
                             normalized_quote: str):
        """Find quote in an indexed document and compute confidence."""
        # Use the inverted index (with space-collapsed fallback)
        normalized_start, normalized_end, strategy = doc.find(normalized_quote)

        position_info = {"original": None, "normalized": None}
        confidence_info = {
            "score": 0.0,
            "level": ConfidenceLevel.NONE,
            "transformations": [],
        }

        if strategy == MatchStrategy.NONE:
            return position_info, confidence_info

        # Map back to original positions
        original_start = doc.position_map[normalized_start]
        original_end = doc.position_map[
            min(normalized_end, len(doc.position_map) - 1)]

        position_info["original"] = Position(
            start=original_start, end=original_end)
        position_info["normalized"] = Position(
            start=normalized_start, end=normalized_end)

        # Extract matched portion and compute transformations
        matched_portion = doc.original_text[original_start:original_end + 1]
        _, _, matched_trans = normalize_with_mapping(matched_portion, self.config)
        _, _, quote_trans = normalize_with_mapping(quote, self.config)

        # Group by type
        matched_by_type = {}
        for t in matched_trans:
            matched_by_type.setdefault(t.type, []).append(t)
        quote_by_type = {}
        for t in quote_trans:
            quote_by_type.setdefault(t.type, []).append(t)

        relevant = []

        # Match strategy transformation
        if strategy == MatchStrategy.COLLAPSED:
            relevant.append(NormalizationTransformation(
                type="collapsed_space_match",
                description="Matched after collapsing spaces (PDF line-break artifact)",
                penalty=self.config.get_penalty("collapsed_space_match"),
            ))

        # Non-stopword transformations
        for ttype, transforms in matched_by_type.items():
            if "stopword" not in ttype and transforms:
                relevant.append(transforms[0])
        for ttype, transforms in quote_by_type.items():
            if "stopword" not in ttype and ttype not in matched_by_type and transforms:
                relevant.append(transforms[0])

        # Stopword difference handling
        matched_removed = set()
        quote_removed = set()
        for t in matched_trans:
            if "stopword_removal" in t.type and t.description:
                words = re.findall(r"Removed [^:]+: ([^']+)", t.description)
                if words:
                    matched_removed.update(words[0].split(", "))
        for t in quote_trans:
            if "stopword_removal" in t.type and t.description:
                words = re.findall(r"Removed [^:]+: ([^']+)", t.description)
                if words:
                    quote_removed.update(words[0].split(", "))

        quote_only = quote_removed - matched_removed
        matched_only = matched_removed - quote_removed

        if quote_only:
            relevant.append(NormalizationTransformation(
                type="stopword_removal_difference",
                description=f"Removed from quote but not from source: {', '.join(quote_only)}",
                penalty=(self.config.get_penalty("stopword_removal")
                         * len(quote_only) / max(1, len(quote.split()))),
            ))
        if matched_only:
            relevant.append(NormalizationTransformation(
                type="stopword_removal_difference",
                description=f"Removed from source but not from quote: {', '.join(matched_only)}",
                penalty=(self.config.get_penalty("stopword_removal")
                         * len(matched_only) / max(1, len(matched_portion.split()))),
            ))

        # Dangerous stopwords — full penalty, not diluted by word count
        dangerous_quote = {
            w for w in quote_only if w.lower() in self.config.dangerous_stopwords}
        dangerous_matched = {
            w for w in matched_only if w.lower() in self.config.dangerous_stopwords}

        if dangerous_quote:
            relevant.append(NormalizationTransformation(
                type="dangerous_stopword_removal_difference",
                description=f"Dangerous words removed from quote but not source: {', '.join(dangerous_quote)}",
                penalty=self.config.get_penalty("dangerous_stopword_removal") * len(dangerous_quote),
            ))
        if dangerous_matched:
            relevant.append(NormalizationTransformation(
                type="dangerous_stopword_removal_difference",
                description=f"Dangerous words removed from source but not quote: {', '.join(dangerous_matched)}",
                penalty=self.config.get_penalty("dangerous_stopword_removal") * len(dangerous_matched),
            ))

        # Compute confidence
        score = 1.0
        for t in relevant:
            score -= t.penalty
        score = max(0.0, min(1.0, score))

        if score > self.config.high_confidence_threshold:
            level = ConfidenceLevel.HIGH
        elif score > self.config.medium_confidence_threshold:
            level = ConfidenceLevel.MEDIUM
        else:
            level = ConfidenceLevel.LOW

        confidence_info["score"] = score
        confidence_info["level"] = level
        confidence_info["transformations"] = relevant

        return position_info, confidence_info

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_context(self, document_text: str, start: int, end: int,
                     context_chars: int = 40) -> dict:
        if (start < 0 or end < 0
                or start >= len(document_text)
                or end >= len(document_text)):
            return {"full": None, "before": "", "after": ""}

        ctx_start = max(0, start - context_chars)
        ctx_end = min(len(document_text), end + context_chars)

        prefix = "..." if ctx_start > 0 else ""
        suffix = "..." if ctx_end < len(document_text) else ""

        before = document_text[ctx_start:start]
        after = document_text[end + 1:ctx_end]
        context = before + document_text[start:end + 1] + document_text[end + 1:ctx_end]

        match_start = start - ctx_start
        match_end = match_start + (end - start) + 1
        full = (prefix + context[:match_start]
                + context[match_start:match_end]
                + context[match_end:] + suffix)

        return {"full": full, "before": before, "after": after}

    def _pre_validate(self, document_text: str, quote: str):
        if not quote.strip():
            return {
                "quote": quote,
                "verified": False,
                "original_position": -1,
                "normalized_position": -1,
                "reason": "Empty quote",
                "length": 0,
            }, False

        if (len(quote.split()) == 1
                and quote.lower() in self.config.stopwords
                and self.config.remove_stopwords):
            return {
                "quote": quote,
                "verified": False,
                "original_position": -1,
                "normalized_position": -1,
                "reason": "Quote consists entirely of stopwords",
                "length": 1,
                "confidence": {"score": 0.0, "level": ConfidenceLevel.NONE},
                "transformations": [{
                    "type": "stopword_removal",
                    "description": f"Quote '{quote}' is a stopword that would be removed",
                    "penalty": 1.0,
                }],
            }, False

        normalized_quote, _, _ = normalize_with_mapping(quote, self.config)
        if not normalized_quote.strip() and quote.strip():
            return {
                "quote": quote,
                "verified": False,
                "original_position": -1,
                "normalized_position": -1,
                "reason": "Quote normalized to empty string",
                "length": len(quote.split()),
                "confidence": {"score": 0.0, "level": ConfidenceLevel.NONE},
                "transformations": [{
                    "type": "excessive_normalization",
                    "description": "Normalization removed all content from quote",
                    "penalty": 1.0,
                }],
            }, False

        return None, True

    # ------------------------------------------------------------------
    # Backward compatibility aliases
    # ------------------------------------------------------------------

    def find_quote_position(self, document_text, quote):
        """Backward compat: auto-indexes text and finds position."""
        doc = self._ensure_indexed_text(document_text)
        nq, _, _ = normalize_with_mapping(quote, self.config)
        return self._find_quote_position(doc, quote, nq)

    def get_context(self, document_text, start_pos, end_pos,
                    context_chars=40):
        return self._get_context(document_text, start_pos, end_pos,
                                 context_chars)

    def pre_validate(self, document_text, quote):
        return self._pre_validate(document_text, quote)
