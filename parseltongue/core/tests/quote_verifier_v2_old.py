import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


class ConfidenceLevel(str, Enum):
    """Enum for confidence levels in quote verification"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass
class NormalizationTransformation:
    """Records a transformation applied during normalization"""
    type: str
    description: str = None
    penalty: float = 0.0


@dataclass
class Position:
    """Positions in text"""
    start: int
    end: int

    def to_dict(self) -> Dict[str, int]:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class VerificationResult:
    """Result of quote verification"""
    quote: str
    verified: bool
    positions: Dict[str, Position] = None
    confidence: Dict = None
    transformations: List[NormalizationTransformation] = None
    length: int = 0
    context: str = None
    reason: str = None
    original_position: int = -1
    normalized_position: int = -1

    def to_dict(self) -> Dict:
        """Convert to dictionary for API compatibility"""
        result = {
            "quote": self.quote,
            "verified": self.verified,
            "original_position": self.original_position,
            "normalized_position": self.normalized_position,
            "length": self.length,
        }

        if self.positions:
            result["positions"] = {
                "original": self.positions.get("original").to_dict() if self.positions.get("original") else None,
                "normalized": self.positions.get("normalized").to_dict() if self.positions.get("normalized") else None
            }

        if self.confidence:
            result["confidence"] = self.confidence

        if self.transformations:
            result["transformations"] = [asdict(t) for t in self.transformations]

        if self.reason:
            result["reason"] = self.reason

        if self.context:
            result["context"] = self.context

        return result


@dataclass
class QuoteVerifierConfig:
    """Configuration for QuoteVerifier, all parameters customizable"""

    # Feature flags
    case_sensitive: bool = False
    ignore_punctuation: bool = True
    normalize_lists: bool = True
    normalize_hyphenation: bool = True
    remove_stopwords: bool = False

    # Verification thresholds
    confidence_threshold: float = 0.7

    high_confidence_threshold: float = 0.9
    medium_confidence_threshold: float = 0.7

    # Transformation penalties - customizable per transformation type
    penalties: Dict[str, float] = field(default_factory=lambda: {
        "whitespace_normalization": 0.001, # This shouldn't change meaning at all
        "whitespace_trimming": 0.001, # This shouldn't change meaning at all
        "hyphenation_normalization": 0.005, # This shouldn't change meaning, and it's very unlikely it would introduce side-effect
        "case_normalization": 0.01, # Very unlikely to introduce potential meaning side-effect
        "list_normalization": 0.01, # Can remove some useful number, but usually would be the number from list due to specific "newline" checks.
        "punctuation_removal": 0.02, # Can affect meaning somewhat but it's extremely unlikely
        # All the items above combined don't make confidence less than high

        "stopword_removal": 0.125, # Regular stopwords removals can introduce changes of meaning. That's why confidence can't be more than medium
        # Any regular stopword removal makes confidence less than high regardless

        "dangerous_stopword_removal": 0.31, # Drops confidence always below medium
        # We are missing some stopword which usually changes meaning to opposite or has critical pivotal meaning
    })

    # Default stopwords
    default_stopwords: Set[str] = field(default_factory=lambda: {
        "a", "an", "the", "this", "that", "these", "those",
        "it", "its", "in", "on", "at", "to", "for", "with", "by", "of",
        'therefore',
        "and", "or", "but", "so", "as", "is", "are", "was", "were"
    })

    # Dangerous stopwords that could change meaning
    dangerous_stopwords: Set[str] = field(default_factory=lambda: {
        "not", "no", "never", "none", "nor", "neither", "without",
        "except", "but", "however", "although", "despite"
    })

    # Custom stopwords provided by user
    custom_stopwords: Set[str] = field(default_factory=set)

    # Combined stopwords for actual use
    stopwords: Set[str] = field(default_factory=set, init=False)

    def __post_init__(self):
        """Combine stopwords appropriately after initialization"""
        if self.remove_stopwords and not self.custom_stopwords:
            # Use default stopwords if none provided
            self.stopwords = self.default_stopwords
        elif self.custom_stopwords:
            # Use custom stopwords if provided
            self.stopwords = self.custom_stopwords
        else:
            # Empty set if stopwords disabled
            self.stopwords = set()

    def get_penalty(self, transformation_type: str) -> float:
        """Get the penalty for a specific transformation type."""
        return self.penalties.get(transformation_type, 0.1)  # Default penalty if not specified

    @classmethod
    def create_with_overrides(cls, **kwargs) -> 'QuoteVerifierConfig':
        """Create a new configuration with overrides from kwargs."""
        # Start with default config
        config = cls()

        # Apply all valid overrides
        for key, value in kwargs.items():
            if hasattr(config, key):
                # Special handling for dictionaries to allow partial updates
                if key == "penalties" and isinstance(value, dict):
                    config.penalties.update(value)
                # Special handling for sets to allow additions
                elif key in ["default_stopwords", "dangerous_stopwords", "custom_stopwords"] and isinstance(value, (
                        set, list)):
                    setattr(config, key, set(value))
                else:
                    setattr(config, key, value)

        # Re-run post-init to update combined stopwords
        config.__post_init__()

        return config


class QuoteVerifier:
    """
    A class to verify if quotes provided by an LLM actually appear in a source document.
    Uses a simplified approach that works reliably even with punctuation differences.
    """

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
        """
        Initialize the QuoteVerifier with configuration options.

        Args:
            case_sensitive: Whether matching should be case-sensitive
            ignore_punctuation: Whether to ignore punctuation when comparing quotes
            normalize_lists: Whether to normalize numbered lists
            normalize_hyphenation: Whether to normalize hyphenation at line breaks
            remove_stopwords: Whether to remove stopwords during normalization
            stopwords: Optional set of stopwords to use. If None and remove_stopwords=True,
                       DEFAULT_STOPWORDS will be used
            confidence_threshold: Minimum confidence score to consider a quote verified
            config: Optional QuoteVerifierConfig object that overrides all other parameters
        """
        # If a config object is provided, use it
        if config is not None:
            self.config = config
        else:
            # Otherwise, create a config from the parameters
            self.config = QuoteVerifierConfig.create_with_overrides(
                case_sensitive=case_sensitive,
                ignore_punctuation=ignore_punctuation,
                normalize_lists=normalize_lists,
                normalize_hyphenation=normalize_hyphenation,
                remove_stopwords=remove_stopwords,
                confidence_threshold=confidence_threshold,
                custom_stopwords=stopwords if stopwords is not None else set()
            )

        # For convenience, create direct references to frequently used config properties
        self._setup_convenience_properties()

    def _setup_convenience_properties(self):
        """Set up convenience properties from config for easy access"""
        self.case_sensitive = self.config.case_sensitive
        self.ignore_punctuation = self.config.ignore_punctuation
        self.normalize_lists = self.config.normalize_lists
        self.normalize_hyphenation = self.config.normalize_hyphenation
        self.remove_stopwords = self.config.remove_stopwords
        self.confidence_threshold = self.config.confidence_threshold
        self.stopwords = self.config.stopwords
        # Keep backward compatibility with class constants
        self.DEFAULT_STOPWORDS = self.config.default_stopwords
        self.DANGEROUS_STOPWORDS = self.config.dangerous_stopwords

    def _normalize_case(self, text: str) -> Tuple[str, List[int], List[NormalizationTransformation]]:
        """Normalize text case (convert to lowercase if case_sensitive=False)"""
        transformations = []

        if not self.config.case_sensitive:
            if any(c.isupper() for c in text):
                transformations.append(NormalizationTransformation(
                    type="case_normalization",
                    description="Converted text to lowercase",
                    penalty=self.config.get_penalty("case_normalization")
                ))

            processed_text = text.lower()
            # Create mapping for lowercase conversion (no position changes)
            position_map = list(range(len(text)))
        else:
            processed_text = text
            position_map = list(range(len(text)))

        return processed_text, position_map, transformations

    def _normalize_lists(self, text: str, position_map: List[int]) -> Tuple[
        str, List[int], List[NormalizationTransformation]]:
        """Normalize numbered lists in text"""
        transformations = []

        if not self.config.normalize_lists:
            return text, position_map, transformations

        normalized_text = ""
        normalized_map = []
        list_items_removed = 0

        i = 0
        while i < len(text):
            # Check if we have a pattern like '\b\d+\.\s+'
            match = re.match(r'\b\d+\.\s+', text[i:])
            if match:
                list_items_removed += 1
                # Skip the list number pattern
                i += len(match.group(0))
                # Add a space instead
                normalized_text += " "
                normalized_map.append(position_map[i - 1])  # Use the position of the last char
            else:
                # No list pattern, keep the character
                normalized_text += text[i]
                normalized_map.append(position_map[i])
                i += 1

        if list_items_removed > 0:
            transformations.append(NormalizationTransformation(
                type="list_normalization",
                description=f"Removed {list_items_removed} list item markers",
                penalty=self.config.get_penalty("list_normalization")
            ))

        return normalized_text, normalized_map, transformations

    def _normalize_hyphenation(self, text: str, position_map: List[int]) -> Tuple[
        str, List[int], List[NormalizationTransformation]]:
        """Normalize hyphenation at line breaks"""
        transformations = []

        if not self.config.normalize_hyphenation:
            return text, position_map, transformations

        normalized_text = ""
        normalized_map = []
        hyphenation_fixed_count = 0

        i = 0
        while i < len(text):
            # Look for hyphenation pattern: word-\n followed by optional spaces and then a word
            if (i < len(text) - 2 and
                    text[i] == '-' and
                    text[i + 1] == '\n'):

                # Check if we have alphanumeric chars before the hyphen
                before_is_alnum = (i > 0 and text[i - 1].isalnum())

                # Skip the hyphen and newline
                i += 2

                # Skip any additional whitespace after the newline
                while i < len(text) and text[i].isspace():
                    i += 1

                # Check if we have alphanumeric chars after the spaces
                after_is_alnum = (i < len(text) and text[i].isalnum())

                if before_is_alnum and after_is_alnum:
                    # Successfully found hyphenation pattern - don't add anything (removing hyphen and spaces)
                    hyphenation_fixed_count += 1
                    continue
                else:
                    # Not a valid hyphenation pattern, so add a space and backtrack
                    normalized_text += " "
                    normalized_map.append(position_map[i - 1])
                    # Need to reprocess from after the newline
                    i = i - 1 if i > 0 else 0

            # Handle regular newlines (convert to space)
            elif text[i] == '\n':
                normalized_text += " "
                normalized_map.append(position_map[i])
                i += 1
            else:
                # Regular character, keep it
                normalized_text += text[i]
                normalized_map.append(position_map[i])
                i += 1

        if hyphenation_fixed_count > 0:
            transformations.append(NormalizationTransformation(
                type="hyphenation_normalization",
                description=f"Fixed {hyphenation_fixed_count} hyphenated word(s) at line breaks",
                penalty=self.config.get_penalty("hyphenation_normalization")
            ))

        return normalized_text, normalized_map, transformations

    def _normalize_punctuation(self, text: str, position_map: List[int]) -> Tuple[
        str, List[int], List[NormalizationTransformation]]:
        """Replace punctuation with spaces"""
        transformations = []

        if not self.config.ignore_punctuation:
            return text, position_map, transformations

        normalized_text = ""
        normalized_map = []
        punctuation_count = 0

        for i, char in enumerate(text):
            if char.isalnum() or char.isspace():
                normalized_text += char
                normalized_map.append(position_map[i])
            else:
                punctuation_count += 1
                normalized_text += " "
                normalized_map.append(position_map[i])

        if punctuation_count > 0:
            transformations.append(NormalizationTransformation(
                type="punctuation_removal",
                description=f"Removed {punctuation_count} punctuation character(s)",
                penalty=self.config.get_penalty("punctuation_removal")
            ))

        return normalized_text, normalized_map, transformations

    def _normalize_stopwords(self, text: str, position_map: List[int]) -> Tuple[
        str, List[int], List[NormalizationTransformation]]:
        """Remove stopwords from text"""
        transformations = []

        if not self.config.remove_stopwords or not self.config.stopwords or not text.strip():
            return text, position_map, transformations

        # First normalize whitespace to get proper word boundaries
        temp_text = re.sub(r'\s+', ' ', text).strip()
        words = temp_text.split()

        # If no words found, return original text
        if not words:
            return text, position_map, transformations

        # Track removed stopwords
        removed_stopwords = []
        removed_dangerous_words = []

        # Check if all words are stopwords
        all_stopwords = all(word.lower() in self.config.stopwords for word in words)
        if all_stopwords:
            # Keep at least one word to prevent empty result
            words_to_keep = [words[0]]
            words_to_remove = words[1:]
            removed_stopwords.extend(words_to_remove)

            # Check for dangerous words in the removed set
            removed_dangerous_words = [w for w in words_to_remove if w.lower() in self.config.dangerous_stopwords]

            transformations.append(NormalizationTransformation(
                type="partial_stopword_removal",
                description=f"Kept one word to prevent empty result, removed {len(words_to_remove)} stopword(s)",
                penalty=self.config.get_penalty("stopword_removal") * 1.5  # Higher penalty for partial removal
            ))

            # Return early with appropriate mapping
            normalized_text = words_to_keep[0]
            # Find the position of this word in the original text
            word_pos = text.lower().find(words_to_keep[0].lower())
            if word_pos >= 0 and word_pos < len(position_map):
                normalized_map = position_map[word_pos:word_pos + len(words_to_keep[0])]
                return normalized_text, normalized_map, transformations
            else:
                # Fallback if position not found
                return normalized_text, position_map[:len(normalized_text)], transformations

        # Rebuild text without stopwords
        normalized_text = ""
        normalized_map = []

        word_start_positions = []
        current_pos = 0
        for word in words:
            # Find the word in the original text
            word_lower = word.lower()
            while current_pos < len(text) and text[current_pos:current_pos + len(word)].lower() != word_lower:
                current_pos += 1

            if current_pos < len(text):
                word_start_positions.append(current_pos)
                current_pos += len(word)

        # Now rebuild text skipping stopwords
        for i, word in enumerate(words):
            if word.lower() in self.config.stopwords:
                removed_stopwords.append(word)
                if word.lower() in self.config.dangerous_stopwords:
                    removed_dangerous_words.append(word)
                continue

            if normalized_text and not normalized_text.endswith(" "):
                normalized_text += " "
                if i > 0 and i - 1 < len(word_start_positions):
                    normalized_map.append(position_map[word_start_positions[i - 1]])

            if i < len(word_start_positions):
                start_pos = word_start_positions[i]
                for j in range(len(word)):
                    if start_pos + j < len(text):
                        normalized_text += text[start_pos + j]
                        normalized_map.append(position_map[start_pos + j])

        # Handle case where all words were stopwords (should not happen with earlier check)
        if not normalized_text.strip() and words:
            normalized_text = words[0]
            word_pos = text.lower().find(words[0].lower())
            if word_pos >= 0 and word_pos < len(position_map):
                normalized_map = position_map[word_pos:word_pos + len(words[0])]
            else:
                normalized_map = position_map[:len(normalized_text)]

        if removed_stopwords:
            if removed_dangerous_words:
                penalty = self.config.get_penalty("dangerous_stopword_removal")
                transformations.append(NormalizationTransformation(
                    type="dangerous_stopword_removal",
                    description=f"Removed potentially meaning-changing words: {', '.join(removed_dangerous_words)}",
                    penalty=penalty
                ))
            else:
                penalty = self.config.get_penalty("stopword_removal")
                transformations.append(NormalizationTransformation(
                    type="stopword_removal",
                    description=f"Removed {len(removed_stopwords)} stopword(s): {', '.join(removed_stopwords)}",
                    penalty=penalty
                ))

        return normalized_text, normalized_map, transformations

    def _normalize_whitespace(self, text: str, position_map: List[int]) -> Tuple[
        str, List[int], List[NormalizationTransformation]]:
        """Normalize whitespace (convert multiple spaces to single, trim leading/trailing)"""
        transformations = []

        # Step 1: Normalize multiple spaces to single spaces
        normalized_text = ""
        normalized_map = []
        whitespace_normalized = False

        in_whitespace = False
        for i, char in enumerate(text):
            if char.isspace():
                if not in_whitespace:
                    normalized_text += " "
                    normalized_map.append(position_map[i])
                    in_whitespace = True
                else:
                    whitespace_normalized = True
            else:
                normalized_text += char
                normalized_map.append(position_map[i])
                in_whitespace = False

        if whitespace_normalized:
            transformations.append(NormalizationTransformation(
                type="whitespace_normalization",
                description="Normalized whitespace",
                penalty=self.config.get_penalty("whitespace_normalization")
            ))

        # Step 2: Trim leading/trailing whitespace
        stripped = normalized_text.strip()
        strip_performed = len(stripped) < len(normalized_text)

        if strip_performed:
            transformations.append(NormalizationTransformation(
                type="whitespace_trimming",
                description="Trimmed leading/trailing whitespace",
                penalty=self.config.get_penalty("whitespace_trimming")
            ))

            start = normalized_text.find(stripped)
            end = start + len(stripped)
            normalized_map = normalized_map[start:end]
            normalized_text = stripped

        return normalized_text, normalized_map, transformations

    def normalize_with_mapping(self, text: str) -> Tuple[str, List[int], List[NormalizationTransformation]]:
        """
        Normalize text while creating a mapping from normalized text positions
        to original text positions.

        Args:
            text: The text to normalize

        Returns:
            Tuple of (normalized_text, position_map, transformations) where:
            - normalized_text is the text after normalization
            - position_map maps each character position in normalized_text to its position in the original text
            - transformations is a list of transformations applied during normalization
        """
        # Handle empty text
        if not text:
            return "", [], []

        all_transformations = []

        # Step 1: Case normalization
        processed_text, position_map, transformations = self._normalize_case(text)
        all_transformations.extend(transformations)

        # Step 2: List normalization
        processed_text, position_map, transformations = self._normalize_lists(processed_text, position_map)
        all_transformations.extend(transformations)

        # Step 3: Hyphenation normalization
        processed_text, position_map, transformations = self._normalize_hyphenation(processed_text, position_map)
        all_transformations.extend(transformations)

        # Step 4: Punctuation normalization
        processed_text, position_map, transformations = self._normalize_punctuation(processed_text, position_map)
        all_transformations.extend(transformations)

        # Step 5: Stopword removal
        processed_text, position_map, transformations = self._normalize_stopwords(processed_text, position_map)
        all_transformations.extend(transformations)

        # Step 6: Whitespace normalization
        processed_text, position_map, transformations = self._normalize_whitespace(processed_text, position_map)
        all_transformations.extend(transformations)

        return processed_text, position_map, all_transformations

    def find_quote_position(self, document_text: str, quote: str) -> Tuple[Dict, Dict]:
        """
        Find the position of a quote in a document, with detailed information.
        This version is fixed to only penalize stopword differences, not matching stopword removals.

        Args:
            document_text: The document text to search in
            quote: The quote to find

        Returns:
            Tuple of (position_info, confidence_info) where:
            - position_info contains original/normalized positions
            - confidence_info contains confidence score and transformation details
        """
        # Normalize document with position mapping
        normalized_doc, doc_position_map, _ = self.normalize_with_mapping(document_text)

        # Normalize quote
        normalized_quote, _, _ = self.normalize_with_mapping(quote)

        # Find the normalized quote in the normalized document
        normalized_position = normalized_doc.find(normalized_quote)

        position_info = {
            "original": None,
            "normalized": None
        }

        confidence_info = {
            "score": 0.0,
            "level": ConfidenceLevel.NONE,
            "transformations": []
        }

        if normalized_position != -1:
            # Map back to position in original document
            original_start = doc_position_map[normalized_position]

            # Calculate end positions
            normalized_end_pos = normalized_position + len(normalized_quote) - 1
            original_end = doc_position_map[min(normalized_end_pos, len(doc_position_map) - 1)]

            position_info["original"] = Position(start=original_start, end=original_end)
            position_info["normalized"] = Position(start=normalized_position, end=normalized_end_pos)

            # Extract the portion of the original document that matched the quote
            matched_portion = document_text[original_start:original_end + 1]

            # Re-run normalization on JUST the matched portion to get precise transformations
            _, _, matched_transformations = self.normalize_with_mapping(matched_portion)

            # Re-run normalization on the quote to get precise transformations
            _, _, quote_transformations = self.normalize_with_mapping(quote)

            # ------ IMPROVED TRANSFORMATION HANDLING ------
            # Group transformations by type
            matched_trans_by_type = {}
            quote_trans_by_type = {}

            for t in matched_transformations:
                if t.type not in matched_trans_by_type:
                    matched_trans_by_type[t.type] = []
                matched_trans_by_type[t.type].append(t)

            for t in quote_transformations:
                if t.type not in quote_trans_by_type:
                    quote_trans_by_type[t.type] = []
                quote_trans_by_type[t.type].append(t)

            # Combine all necessary transformations
            relevant_transformations = []

            # Handle non-stopword transformations (use unique transformations by type)
            for trans_type, transforms in matched_trans_by_type.items():
                if "stopword" not in trans_type:
                    # For non-stopword transformations, just use the first one of each type
                    if transforms:
                        relevant_transformations.append(transforms[0])

            for trans_type, transforms in quote_trans_by_type.items():
                if "stopword" not in trans_type and trans_type not in matched_trans_by_type:
                    # Add unique transformation types from quote side
                    if transforms:
                        relevant_transformations.append(transforms[0])

            # ------ SPECIAL HANDLING FOR STOPWORD TRANSFORMATIONS ------
            matched_removed_words = set()
            quote_removed_words = set()

            # Extract removed stopwords from matched portion
            for t in matched_transformations:
                if "stopword_removal" in t.type and t.description:
                    words = re.findall(r"Removed [^:]+: ([^']+)", t.description)
                    if words:
                        matched_removed_words.update(set(words[0].split(", ")))

            # Extract removed stopwords from quote
            for t in quote_transformations:
                if "stopword_removal" in t.type and t.description:
                    words = re.findall(r"Removed [^:]+: ([^']+)", t.description)
                    if words:
                        quote_removed_words.update(set(words[0].split(", ")))

            # Find stopwords removed ONLY in quote but not in matched text
            quote_only_removed = quote_removed_words - matched_removed_words
            # Find stopwords removed ONLY in matched text but not in quote
            matched_only_removed = matched_removed_words - quote_removed_words

            # Only penalize for differences in stopword removal
            if quote_only_removed:
                # Words removed from quote but present in original
                relevant_transformations.append(NormalizationTransformation(
                    type="stopword_removal_difference",
                    description=f"Removed from quote but not from source: {', '.join(quote_only_removed)}",
                    penalty=self.config.get_penalty("stopword_removal") * len(quote_only_removed) /
                            max(1, len(quote.split()))
                ))

            if matched_only_removed:
                # Words removed from original but present in quote
                relevant_transformations.append(NormalizationTransformation(
                    type="stopword_removal_difference",
                    description=f"Removed from source but not from quote: {', '.join(matched_only_removed)}",
                    penalty=self.config.get_penalty("stopword_removal") * len(matched_only_removed) /
                            max(1, len(matched_portion.split()))
                ))

            # Check for dangerous stopwords specifically
            dangerous_in_quote_only = {word for word in quote_only_removed
                                       if word.lower() in self.config.dangerous_stopwords}
            dangerous_in_matched_only = {word for word in matched_only_removed
                                         if word.lower() in self.config.dangerous_stopwords}

            if dangerous_in_quote_only:
                relevant_transformations.append(NormalizationTransformation(
                    type="dangerous_stopword_removal_difference",
                    description=f"Dangerous words removed from quote but not source: {', '.join(dangerous_in_quote_only)}",
                    penalty=self.config.get_penalty("dangerous_stopword_removal") * len(dangerous_in_quote_only) /
                            max(1, len(quote.split()))
                ))

            if dangerous_in_matched_only:
                relevant_transformations.append(NormalizationTransformation(
                    type="dangerous_stopword_removal_difference",
                    description=f"Dangerous words removed from source but not quote: {', '.join(dangerous_in_matched_only)}",
                    penalty=self.config.get_penalty("dangerous_stopword_removal") * len(dangerous_in_matched_only) /
                            max(1, len(matched_portion.split()))
                ))

            # Calculate confidence based only on relevant transformations
            confidence_score = 1.0

            for transformation in relevant_transformations:
                confidence_score -= transformation.penalty

            confidence_score = max(0.0, min(1.0, confidence_score))

            # Use config thresholds for confidence levels
            if confidence_score > self.config.high_confidence_threshold:
                confidence_level = ConfidenceLevel.HIGH
            elif confidence_score > self.config.medium_confidence_threshold:
                confidence_level = ConfidenceLevel.MEDIUM
            else:
                confidence_level = ConfidenceLevel.LOW

            confidence_info["score"] = confidence_score
            confidence_info["level"] = confidence_level
            confidence_info["transformations"] = relevant_transformations

        return position_info, confidence_info

    def get_context(self, document_text: str, start_pos: int, end_pos: int, context_chars: int = 40) -> dict:
        """
        Get context around the matched position in the original document.

        Args:
            document_text: The original document text
            start_pos: Start position of the match
            end_pos: End position of the match
            context_chars: Number of characters to include before and after

        Returns:
            Dictionary with 'full', 'before', and 'after' context
        """
        if start_pos < 0 or end_pos < 0 or start_pos >= len(document_text) or end_pos >= len(document_text):
            return {"full": None, "before": "", "after": ""}

        context_start = max(0, start_pos - context_chars)
        context_end = min(len(document_text), end_pos + context_chars)

        prefix = "..." if context_start > 0 else ""
        suffix = "..." if context_end < len(document_text) else ""

        # Get separate before/after context
        context_before = document_text[context_start:start_pos]
        context_after = document_text[end_pos + 1:context_end]

        # Get the full text with context
        context = context_before + document_text[start_pos:end_pos + 1] + document_text[end_pos + 1:context_end]

        # Format the matched part with markers
        match_start_offset = start_pos - context_start
        match_end_offset = match_start_offset + (end_pos - start_pos) + 1

        context_with_markers = prefix + context[:match_start_offset] \
                               + context[match_start_offset:match_end_offset] \
                               + context[match_end_offset:] + suffix

        return {
            "full": context_with_markers,
            "before": context_before,
            "after": context_after
        }

    def pre_validate(self, document_text: str, quote: str):
        if not quote.strip():
            return {
                "quote": quote,
                "verified": False,
                "original_position": -1,
                "normalized_position": -1,
                "reason": "Empty quote",
                "length": 0
            }, False

        # Check for degenerate cases
        if len(quote.split()) == 1 and quote.lower() in self.config.stopwords and self.config.remove_stopwords:
            return {
                "quote": quote,
                "verified": False,
                "original_position": -1,
                "normalized_position": -1,
                "reason": "Quote consists entirely of stopwords",
                "length": 1,
                "confidence": {
                    "score": 0.0,
                    "level": ConfidenceLevel.NONE
                },
                "transformations": [{
                    "type": "stopword_removal",
                    "description": f"Quote '{quote}' is a stopword that would be removed",
                    "penalty": 1.0
                }]
            }, False
        # Normalize quote for length calculation
        normalized_quote, _, _ = self.normalize_with_mapping(quote)

        # Handle case where normalization emptied the quote
        if not normalized_quote.strip() and quote.strip():
            return {
                "quote": quote,
                "verified": False,
                "original_position": -1,
                "normalized_position": -1,
                "reason": "Quote normalized to empty string",
                "length": len(quote.split()),
                "confidence": {
                    "score": 0.0,
                    "level": ConfidenceLevel.NONE
                },
                "transformations": [{
                    "type": "excessive_normalization",
                    "description": "Normalization removed all content from quote",
                    "penalty": 1.0
                }]
            }, False

        return None, True

    def verify_quote(self, document_text: str, quote: str, context_length: int = 40) -> Dict:
        """
        Verify if a quote appears in the document text.

        Args:
            document_text: The document text to search in
            quote: The quote to verify
            context_length: Number of characters to include before and after the match for context

        Returns:
            Dictionary with verification results including confidence scoring
        """
        return_obj, validation = self.pre_validate(document_text, quote)
        if not validation:
            return return_obj

        normalized_quote, _, _ = self.normalize_with_mapping(quote)
        position_info, confidence_info = self.find_quote_position(document_text, quote)

        verified = (position_info["original"] is not None and
                    confidence_info["score"] >= self.config.confidence_threshold)

        # Get original positions for backward compatibility
        original_position = position_info["original"].start if position_info["original"] else -1
        normalized_position = position_info["normalized"].start if position_info["normalized"] else -1

        context = None
        if position_info["original"]:
            context = self.get_context(
                document_text,
                position_info["original"].start,
                position_info["original"].end,
                context_length
            )

        # Build result with backward compatibility
        result = {
            "quote": quote,
            "verified": verified,
            "original_position": original_position,
            "normalized_position": normalized_position,
            "length": len(normalized_quote.split()) if normalized_quote.strip() else len(quote.split())
        }

        # Add enhanced information
        if position_info["original"]:
            result["positions"] = {
                "original": {
                    "start": position_info["original"].start,
                    "end": position_info["original"].end
                },
                "normalized": {
                    "start": position_info["normalized"].start,
                    "end": position_info["normalized"].end
                }
            }

        # Add confidence information
        result["confidence"] = {
            "score": confidence_info["score"],
            "level": confidence_info["level"]
        }

        # Add transformations if any
        if confidence_info["transformations"]:
            result["transformations"] = [
                {
                    "type": t.type,
                    "description": t.description,
                    "penalty": t.penalty
                } for t in confidence_info["transformations"]
            ]

        # Add context if available
        if context:
            result["context"] = context

        # Add reason if not verified
        if not verified:
            if original_position != -1:
                result["reason"] = "Below confidence threshold"
            else:
                result["reason"] = "Not found in document"

        return result

    def verify_quotes(self, document_text: str, quotes: List[str]) -> List[Dict]:
        """
        Verify multiple quotes against a document.

        Args:
            document_text: The document text to search in
            quotes: List of quotes to verify

        Returns:
            List of verification results for each quote
        """
        return [self.verify_quote(document_text, quote) for quote in quotes]
