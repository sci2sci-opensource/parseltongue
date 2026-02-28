"""Quote Verifier — Types and Configuration."""

import re
from typing import List, Dict, Tuple, Set, Optional
from dataclasses import dataclass, asdict, field
from enum import Enum


class ConfidenceLevel(str, Enum):
    """Enum for confidence levels in quote verification."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class MatchStrategy(str, Enum):
    """How a quote was matched against the document."""
    EXACT = "exact"              # Inverted index hit — word boundaries align
    COLLAPSED = "collapsed"      # Matched after removing spaces (PDF line-break artifacts)
    NONE = "none"                # No match found


@dataclass
class NormalizationTransformation:
    """Records a transformation applied during normalization."""
    type: str
    description: str = None
    penalty: float = 0.0


@dataclass
class Position:
    """Positions in text."""
    start: int
    end: int

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


@dataclass
class QuoteVerifierConfig:
    """Configuration for QuoteVerifier, all parameters customizable."""

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

    # Transformation penalties
    penalties: Dict[str, float] = field(default_factory=lambda: {
        "whitespace_normalization": 0.001,
        "whitespace_trimming": 0.001,
        "hyphenation_normalization": 0.005,
        "case_normalization": 0.01,
        "list_normalization": 0.01,
        "punctuation_removal": 0.02,
        "collapsed_space_match": 0.03,
        "stopword_removal": 0.125,
        "dangerous_stopword_removal": 0.31,
    })

    # Stopword sets
    default_stopwords: Set[str] = field(default_factory=lambda: {
        "a", "an", "the", "this", "that", "these", "those",
        "it", "its", "in", "on", "at", "to", "for", "with", "by", "of",
        "therefore",
        "and", "or", "but", "so", "as", "is", "are", "was", "were"
    })

    dangerous_stopwords: Set[str] = field(default_factory=lambda: {
        "not", "no", "never", "none", "nor", "neither", "without",
        "except", "but", "however", "although", "despite"
    })

    custom_stopwords: Set[str] = field(default_factory=set)
    stopwords: Set[str] = field(default_factory=set, init=False)

    def __post_init__(self):
        if self.remove_stopwords and not self.custom_stopwords:
            self.stopwords = self.default_stopwords
        elif self.custom_stopwords:
            self.stopwords = self.custom_stopwords
        else:
            self.stopwords = set()

    def get_penalty(self, transformation_type: str) -> float:
        return self.penalties.get(transformation_type, 0.1)

    @classmethod
    def create_with_overrides(cls, **kwargs) -> 'QuoteVerifierConfig':
        config = cls()
        for key, value in kwargs.items():
            if hasattr(config, key):
                if key == "penalties" and isinstance(value, dict):
                    config.penalties.update(value)
                elif key in ["default_stopwords", "dangerous_stopwords", "custom_stopwords"] and isinstance(value, (set, list)):
                    setattr(config, key, set(value))
                else:
                    setattr(config, key, value)
        config.__post_init__()
        return config
