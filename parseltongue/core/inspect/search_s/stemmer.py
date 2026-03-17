"""Suffix stemmer — lightweight English stemming via rule table.

No dependencies. Operates on already-normalized (lowercased, punctuation-stripped)
tokens from IndexedDocument. Not a full Porter stemmer — just the high-value
suffix rules that cover most code-relevant English.

Rules are applied longest-match-first. Each rule: (suffix, replacement, min_stem).
min_stem ensures we don't over-strip short words (e.g. "ing" won't strip "ring").
"""

from __future__ import annotations

# (suffix, replacement, min_stem_length)
# Ordered by suffix length descending within each group.
_RULES: list[tuple[str, str, int]] = [
    # -tion / -sion → -t / -s (longer suffixes first)
    ("isation", "ise", 3),
    ("ization", "ize", 3),
    ("ation", "ate", 3),
    ("tion", "t", 3),
    ("sion", "s", 3),
    # -ing
    ("pping", "p", 3),
    ("tting", "t", 3),
    ("nning", "n", 3),
    ("gging", "g", 3),
    ("dding", "d", 3),
    ("lling", "ll", 2),
    ("ssing", "ss", 2),
    ("ying", "y", 2),
    ("eing", "e", 2),
    ("ing", "", 3),
    # -ed
    ("pped", "p", 3),
    ("tted", "t", 3),
    ("nned", "n", 3),
    ("gged", "g", 3),
    ("dded", "d", 3),
    ("lled", "ll", 2),
    ("ssed", "ss", 2),
    ("ied", "y", 2),
    ("eed", "ee", 2),
    ("ed", "", 3),
    # -ly
    ("ously", "ous", 3),
    ("ively", "ive", 3),
    ("ably", "able", 2),
    ("ibly", "ible", 2),
    ("ally", "al", 3),
    ("ily", "y", 3),
    ("ly", "", 3),
    # -er / -est
    ("ier", "y", 3),
    ("iest", "y", 3),
    ("er", "", 3),
    ("est", "", 3),
    # -ness
    ("iness", "y", 3),
    ("ness", "", 3),
    # -ment
    ("ment", "", 3),
    # -able / -ible
    ("able", "", 3),
    ("ible", "", 3),
    # -ful / -less
    ("ful", "", 3),
    ("less", "", 3),
    # -ous
    ("eous", "e", 3),
    ("ious", "e", 3),
    ("ous", "", 3),
    # -ive
    ("ative", "ate", 3),
    ("ive", "", 3),
    # -ize / -ise
    ("ize", "", 3),
    ("ise", "", 3),
    # plural
    ("ies", "y", 2),
    ("sses", "ss", 2),
    ("xes", "x", 2),
    ("zes", "z", 2),
    ("ches", "ch", 2),
    ("shes", "sh", 2),
    ("s", "", 3),
]


def stem(word: str) -> str:
    """Stem a single normalized token. Returns the stem."""
    if len(word) <= 2:
        return word
    for suffix, replacement, min_stem in _RULES:
        if word.endswith(suffix):
            stem_part = word[: -len(suffix)]
            if len(stem_part) >= min_stem:
                return stem_part + replacement
    return word


def stem_tokens(tokens: list[str]) -> list[str]:
    """Stem a list of tokens."""
    return [stem(t) for t in tokens]
