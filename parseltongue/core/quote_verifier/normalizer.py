"""Quote Verifier — Normalization Pipeline.

Six-step normalization: case, lists, hyphenation, punctuation, stopwords, whitespace.
All functions are stateless — they take config as a parameter.

Penalty formulas:
    Flat penalty — each step calls config.get_penalty(type) with no scaling.
    All-stopwords — when all words are stopwords, keeps first word and applies
        penalty = config.get_penalty("stopword_removal") * 1.5 multiplier.
"""

import re
from typing import List, Tuple

from .config import NormalizationTransformation, QuoteVerifierConfig


def normalize_with_mapping(
    text: str,
    config: QuoteVerifierConfig,
) -> Tuple[str, List[int], List[NormalizationTransformation]]:
    """Normalize text while creating a position map back to the original.

    Returns (normalized_text, position_map, transformations).
    """
    if not text:
        return "", [], []

    all_transformations = []

    processed, pos_map, trans = _normalize_case(text, config)
    all_transformations.extend(trans)

    processed, pos_map, trans = _normalize_lists(processed, pos_map, config)
    all_transformations.extend(trans)

    processed, pos_map, trans = _normalize_hyphenation(processed, pos_map, config)
    all_transformations.extend(trans)

    processed, pos_map, trans = _normalize_punctuation(processed, pos_map, config)
    all_transformations.extend(trans)

    processed, pos_map, trans = _normalize_stopwords(processed, pos_map, config)
    all_transformations.extend(trans)

    processed, pos_map, trans = _normalize_whitespace(processed, pos_map, config)
    all_transformations.extend(trans)

    return processed, pos_map, all_transformations


# ------------------------------------------------------------------
# Individual normalization steps
# ------------------------------------------------------------------


def _normalize_case(
    text: str,
    config: QuoteVerifierConfig,
) -> Tuple[str, List[int], List[NormalizationTransformation]]:
    transformations = []
    if not config.case_sensitive:
        if any(c.isupper() for c in text):
            transformations.append(
                NormalizationTransformation(
                    type="case_normalization",
                    description="Converted text to lowercase",
                    penalty=config.get_penalty("case_normalization"),
                )
            )
        processed = text.lower()
    else:
        processed = text
    position_map = list(range(len(text)))
    return processed, position_map, transformations


def _normalize_lists(
    text: str,
    position_map: List[int],
    config: QuoteVerifierConfig,
) -> Tuple[str, List[int], List[NormalizationTransformation]]:
    transformations: list[NormalizationTransformation] = []
    if not config.normalize_lists:
        return text, position_map, transformations

    normalized_text = ""
    normalized_map = []
    list_items_removed = 0
    i = 0
    _list_re = re.compile(r"([12]?\d)\.\s+")

    while i < len(text):
        match = _list_re.match(text, i)
        line_start = text.rfind("\n", 0, i) + 1
        prefix = text[line_start:i]
        at_line_start = prefix == "" or (len(prefix) >= 2 and prefix.strip() == "")
        if match and at_line_start:
            list_items_removed += 1
            i += len(match.group(0))
            normalized_text += " "
            normalized_map.append(position_map[i - 1])
        else:
            normalized_text += text[i]
            normalized_map.append(position_map[i])
            i += 1

    if list_items_removed > 0:
        transformations.append(
            NormalizationTransformation(
                type="list_normalization",
                description=f"Removed {list_items_removed} list item markers",
                penalty=config.get_penalty("list_normalization"),
            )
        )

    return normalized_text, normalized_map, transformations


def _normalize_hyphenation(
    text: str,
    position_map: List[int],
    config: QuoteVerifierConfig,
) -> Tuple[str, List[int], List[NormalizationTransformation]]:
    transformations: list[NormalizationTransformation] = []
    if not config.normalize_hyphenation:
        return text, position_map, transformations

    normalized_text = ""
    normalized_map = []
    count = 0
    i = 0

    while i < len(text):
        if i < len(text) - 2 and text[i] == "-" and text[i + 1] == "\n":
            before_alnum = i > 0 and text[i - 1].isalnum()
            i += 2
            while i < len(text) and text[i].isspace():
                i += 1
            after_alnum = i < len(text) and text[i].isalnum()
            if before_alnum and after_alnum:
                count += 1
                continue
            else:
                normalized_text += " "
                normalized_map.append(position_map[i - 1])
                i = i - 1 if i > 0 else 0
        elif text[i] == "\n":
            normalized_text += " "
            normalized_map.append(position_map[i])
            i += 1
        else:
            normalized_text += text[i]
            normalized_map.append(position_map[i])
            i += 1

    if count > 0:
        transformations.append(
            NormalizationTransformation(
                type="hyphenation_normalization",
                description=f"Fixed {count} hyphenated word(s) at line breaks",
                penalty=config.get_penalty("hyphenation_normalization"),
            )
        )

    return normalized_text, normalized_map, transformations


def _next_alnum(text: str, i: int) -> bool:
    """Check if the next non-whitespace character after position i is alphanumeric."""
    j = i + 1
    while j < len(text) and text[j].isspace():
        j += 1
    return j < len(text) and text[j].isalnum()


def _normalize_punctuation(
    text: str,
    position_map: List[int],
    config: QuoteVerifierConfig,
) -> Tuple[str, List[int], List[NormalizationTransformation]]:
    transformations: list[NormalizationTransformation] = []
    if not config.ignore_punctuation:
        return text, position_map, transformations

    # Only strip actual prose punctuation — not operator/math symbols
    _PUNCTUATION = set('.,;:?\'"()[]{}…—–-`\u2018\u2019\u201c\u201d\u00ab\u00bb\u00a0\u2007\u202f')

    normalized_text = ""
    normalized_map = []
    count = 0

    for i, char in enumerate(text):
        if char not in _PUNCTUATION:
            normalized_text += char
            normalized_map.append(position_map[i])
        elif char == "-" and i > 0 and text[i - 1].isalnum() and _next_alnum(text, i):
            # Keep attached hyphens (e.g. "multi-level") — they're word structure
            normalized_text += char
            normalized_map.append(position_map[i])
        elif char in ",." and i > 0 and text[i - 1].isalnum() and i + 1 < len(text) and text[i + 1].isalnum():
            # Keep commas/dots immediately between alphanums (150,000  3.14)
            normalized_text += char
            normalized_map.append(position_map[i])
        else:
            count += 1
            normalized_text += " "
            normalized_map.append(position_map[i])

    if count > 0:
        transformations.append(
            NormalizationTransformation(
                type="punctuation_removal",
                description=f"Removed {count} punctuation character(s)",
                penalty=config.get_penalty("punctuation_removal"),
            )
        )

    return normalized_text, normalized_map, transformations


def _normalize_stopwords(
    text: str,
    position_map: List[int],
    config: QuoteVerifierConfig,
) -> Tuple[str, List[int], List[NormalizationTransformation]]:
    transformations: list[NormalizationTransformation] = []
    if not config.remove_stopwords or not config.stopwords or not text.strip():
        return text, position_map, transformations

    temp_text = re.sub(r"\s+", " ", text).strip()
    words = temp_text.split()
    if not words:
        return text, position_map, transformations

    removed_stopwords = []
    removed_dangerous_words = []

    # All words are stopwords — keep at least one
    all_stopwords = all(w.lower() in config.stopwords for w in words)
    if all_stopwords:
        words_to_keep = [words[0]]
        words_to_remove = words[1:]
        removed_stopwords.extend(words_to_remove)
        removed_dangerous_words = [w for w in words_to_remove if w.lower() in config.dangerous_stopwords]
        transformations.append(
            NormalizationTransformation(
                type="partial_stopword_removal",
                description=f"Kept one word to prevent empty result, removed {len(words_to_remove)} stopword(s)",
                penalty=config.get_penalty("stopword_removal") * 1.5,
            )
        )
        normalized_text = words_to_keep[0]
        word_pos = text.lower().find(words_to_keep[0].lower())
        if 0 <= word_pos < len(position_map):
            normalized_map = position_map[word_pos : word_pos + len(words_to_keep[0])]
            return normalized_text, normalized_map, transformations
        else:
            return normalized_text, position_map[: len(normalized_text)], transformations

    # Find word positions in original text
    word_start_positions = []
    current_pos = 0
    for word in words:
        word_lower = word.lower()
        while current_pos < len(text) and text[current_pos : current_pos + len(word)].lower() != word_lower:
            current_pos += 1
        if current_pos < len(text):
            word_start_positions.append(current_pos)
            current_pos += len(word)

    # Rebuild without stopwords
    normalized_text = ""
    normalized_map = []

    for i, word in enumerate(words):
        if word.lower() in config.stopwords:
            removed_stopwords.append(word)
            if word.lower() in config.dangerous_stopwords:
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

    # Fallback if all removed
    if not normalized_text.strip() and words:
        normalized_text = words[0]
        word_pos = text.lower().find(words[0].lower())
        if 0 <= word_pos < len(position_map):
            normalized_map = position_map[word_pos : word_pos + len(words[0])]
        else:
            normalized_map = position_map[: len(normalized_text)]

    if removed_stopwords:
        if removed_dangerous_words:
            transformations.append(
                NormalizationTransformation(
                    type="dangerous_stopword_removal",
                    description=f"Removed potentially meaning-changing words: {', '.join(removed_dangerous_words)}",
                    penalty=config.get_penalty("dangerous_stopword_removal"),
                )
            )
        else:
            transformations.append(
                NormalizationTransformation(
                    type="stopword_removal",
                    description=f"Removed {len(removed_stopwords)} stopword(s): {', '.join(removed_stopwords)}",
                    penalty=config.get_penalty("stopword_removal"),
                )
            )

    return normalized_text, normalized_map, transformations


def _normalize_whitespace(
    text: str,
    position_map: List[int],
    config: QuoteVerifierConfig,
) -> Tuple[str, List[int], List[NormalizationTransformation]]:
    transformations = []

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
        transformations.append(
            NormalizationTransformation(
                type="whitespace_normalization",
                description="Normalized whitespace",
                penalty=config.get_penalty("whitespace_normalization"),
            )
        )

    stripped = normalized_text.strip()
    if len(stripped) < len(normalized_text):
        transformations.append(
            NormalizationTransformation(
                type="whitespace_trimming",
                description="Trimmed leading/trailing whitespace",
                penalty=config.get_penalty("whitespace_trimming"),
            )
        )
        start = normalized_text.find(stripped)
        end = start + len(stripped)
        normalized_map = normalized_map[start:end]
        normalized_text = stripped

    return normalized_text, normalized_map, transformations
