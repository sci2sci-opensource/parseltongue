"""BM25 ranking for search results.

Document-level BM25 with meta boost overlay. Each posting entry gets a
``_score`` field combining:
    BM25(query, doc) × meta_boost(query, doc)

Standard BM25 parameters: k1=1.2, b=0.75.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

from .stemmer import stem
from .synonyms import DEFAULT_SYNONYMS, ExpansionScope

if TYPE_CHECKING:
    from .index import DocumentSearchIndex


def _name_tokens(name: str) -> set[str]:
    """Split doc name into stemmed tokens: 'lang.py' → {'lang', 'py'}."""
    return {stem(t) for t in re.split(r"[.\-_/: ]+", name.lower()) if t}


def bm25_score(
    index: "DocumentSearchIndex",
    query_tokens: list[str],
    *,
    k1: float = 1.2,
    b: float = 0.75,
) -> dict[str, float]:
    """Compute BM25 score per document with per-hit boosting.

    For each query token (expanded via synonyms, OR semantics):
    - Content hits: TF from stem_to_lines
    - Name hits: synthetic TF boost for doc name matches
    - Meta hits: query-aware annotation boost applied per hit

    Boost is inside the sum, not after — standard BM25 field boosting.

    Returns {doc_name: score}.
    """
    N = len(index.documents)
    if N == 0:
        return {}

    doc_lengths: dict[str, int] = {}
    for name, sdoc in index.documents.items():
        doc_lengths[name] = sum(len(lines) for lines in sdoc.word_to_lines.values())
    avgdl = sum(doc_lengths.values()) / N if N else 1

    # Expand each query token via synonyms
    expanded_stems: list[list[tuple[str, float]]] = []
    for t in query_tokens:
        synonyms = DEFAULT_SYNONYMS.expand(t, scope=ExpansionScope.UNIVERSAL)
        expanded_stems.append([(stem(e.term), e.weight) for e in synonyms])

    # Pre-compute per-doc: name stems and meta boost per query token
    doc_name_stems: dict[str, set[str]] = {name: _name_tokens(name) for name in index.documents}
    doc_meta_boost: dict[str, float] = {}
    for name, sdoc in index.documents.items():
        matching = sdoc.meta.matches_query(query_tokens)
        if matching:
            doc_meta_boost[name] = sum(m.weight for m in matching)

    scores: dict[str, float] = {name: 0.0 for name in index.documents}

    for term_group in expanded_stems:
        for name, sdoc in index.documents.items():
            dl = doc_lengths[name]
            best_contribution = 0.0

            for t, syn_weight in term_group:
                tf = len(sdoc.stem_to_lines.get(t, set()))

                # Name match: synthetic TF
                if t in doc_name_stems[name]:
                    tf += 10

                if tf == 0:
                    continue

                df = sum(
                    1 for s_name, s in index.documents.items() if t in s.stem_to_lines or t in doc_name_stems[s_name]
                )
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)

                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * dl / avgdl)

                # Per-hit boost: synonym weight × meta boost
                hit_boost = syn_weight * doc_meta_boost.get(name, 1.0)
                contribution = idf * numerator / denominator * hit_boost

                best_contribution = max(best_contribution, contribution)

            scores[name] += best_contribution

    return scores


def line_score(
    index: "DocumentSearchIndex",
    doc_name: str,
    line_num: int,
    query_tokens: list[str],
) -> float:
    """Score a single line by how many query terms (or synonyms) it contains.

    Returns a 0–1 ratio: matched_terms / total_query_terms.
    Each term uses best synonym match (weighted).
    """
    sdoc = index.documents.get(doc_name)
    if not sdoc or line_num < 1 or line_num > len(sdoc.lines):
        return 0.0

    score = 0.0
    for t in query_tokens:
        synonyms = DEFAULT_SYNONYMS.expand(t, scope=ExpansionScope.UNIVERSAL)
        best = 0.0
        for entry in synonyms:
            s = stem(entry.term)
            if s in sdoc.stem_to_lines and line_num in sdoc.stem_to_lines[s]:
                best = max(best, entry.weight)
        score += best

    return score / len(query_tokens) if query_tokens else 0.0


def rank_postings(
    index: "DocumentSearchIndex",
    posting: dict,
    query_tokens: list[str],
) -> dict:
    """Score and sort by doc-level BM25 × line-level term coverage.

    _score = bm25(doc) × line_score(line). Lines with more query term
    hits rank higher within the same document.
    """
    if not posting:
        return posting

    doc_scores = bm25_score(index, query_tokens)

    for (doc_name, line_num), entry in posting.items():
        bm25 = doc_scores.get(doc_name, 0.0)
        ls = line_score(index, doc_name, line_num, query_tokens)
        entry["_score"] = round(bm25 * ls, 4) if ls > 0 else round(bm25 * 0.01, 4)

    return dict(sorted(posting.items(), key=lambda x: (-x[1]["_score"], x[0][0], x[0][1])))


def rrf(ranked_lists: list[dict], k: int = 60) -> dict:
    """Reciprocal Rank Fusion across multiple posting dicts.

    Each posting dict is treated as a ranked list (insertion order).
    Score per key = Σ 1/(k + rank) across all lists where it appears.

    Returns a merged posting dict sorted by RRF score descending,
    with ``_rrf`` attached to each entry.
    """
    scores: dict[tuple, float] = {}
    entries: dict[tuple, dict] = {}

    for posting in ranked_lists:
        for rank, (key, entry) in enumerate(posting.items(), 1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in entries:
                entries[key] = entry

    for key, entry in entries.items():
        entry["_rrf"] = round(scores[key], 6)

    return dict(sorted(entries.items(), key=lambda x: -x[1]["_rrf"]))
