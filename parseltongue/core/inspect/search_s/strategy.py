"""Search strategy — cascade: direct → stemmed → n-gram → meta.

Each strategy level produces a posting set. The cascade tries
levels in order, returning the first non-empty result. Alternatively,
``merge`` runs all levels and combines with decreasing confidence weights.

Synonym expansion is scoped:
    DOCUMENTS — expanded tokens hit content indices only
    META      — expanded tokens hit meta indices + originals get direct boost
    UNIVERSAL — both paths

Strategies:
    direct   — exact normalized word/phrase match via word_to_lines
    stemmed  — stem query tokens, match against stem_to_lines
    ngram    — bigram/trigram overlap, ranked by Jaccard similarity
    meta     — match against document metadata (name, tags, etc.)
    expanded — synonym-expanded search across content + meta

The ``(strategy ...)`` operator in the search system wires into this.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from parseltongue.core.quote_verifier.config import QuoteVerifierConfig
from parseltongue.core.quote_verifier.normalizer import normalize_with_mapping

from .stemmer import stem
from .synonyms import DEFAULT_SYNONYMS, ExpansionScope, SynonymIndex

# Shared config for query normalization — default + dangerous stopwords
__base = QuoteVerifierConfig()
_QUERY_CONFIG = QuoteVerifierConfig(
    remove_stopwords=True,
    custom_stopwords=__base.default_stopwords | __base.dangerous_stopwords,
)

if TYPE_CHECKING:
    from .index import DocumentSearchIndex

# Confidence weights for cascade merge
WEIGHT_DIRECT = 1.0
WEIGHT_STEMMED = 0.7
WEIGHT_NGRAM = 0.4
WEIGHT_META = 0.5
WEIGHT_EXPANDED = 0.6


def _tokenize_query(query: str) -> list[str]:
    """Normalize and tokenize a query string.

    Same pipeline as document indexing: normalize, split, then expand
    compound tokens into shingles via _COMPOUND_SPLIT (shared with
    SearchDocument). Compound parts replace the original token — all
    parts must co-occur (AND via lines_with_all_words).

    "errors in lang"       → ["errors", "lang"]
    "operations_v2"        → ["operations_v2", "operations", "v2"]
    "sys.ops_v2 raise"     → ["sys.ops_v2", "sys", "ops", "v2", "raise"]
    "xyzzy_not_here_42"    → ["xyzzy_not_here_42", "xyzzy", "not", "here", "42"]
    """
    from .document import _COMPOUND_SPLIT

    normalized, _, _ = normalize_with_mapping(query, _QUERY_CONFIG)
    result = []
    for t in normalized.split():
        result.append(t)
        parts = _COMPOUND_SPLIT.split(t)
        if len(parts) > 1:
            result.extend(p for p in parts if p)
    return result


def _make_posting(doc_name: str, line_num: int, lines: list[str], **extra) -> dict:
    """Build a single posting entry."""
    entry = {
        "document": doc_name,
        "line": line_num,
        "column": 1,
        "context": lines[line_num - 1] if 1 <= line_num <= len(lines) else "",
        "callers": [],
        "total_callers": 0,
    }
    entry.update(extra)
    return entry


def search_direct(index: "DocumentSearchIndex", query: str) -> dict:
    """Exact normalized match — word_to_lines intersection."""
    tokens = _tokenize_query(query)
    if not tokens:
        return {}
    result = {}
    for doc_name, sdoc in index.documents.items():
        for line_num in sdoc.lines_with_all_words(tokens):
            if line_num <= len(sdoc.lines):
                result[(doc_name, line_num)] = _make_posting(doc_name, line_num, sdoc.lines)
    return result


def search_stemmed(index: "DocumentSearchIndex", query: str) -> dict:
    """Stemmed match — stem query tokens, intersect stem_to_lines."""
    tokens = _tokenize_query(query)
    if not tokens:
        return {}
    result = {}
    for doc_name, sdoc in index.documents.items():
        for line_num in sdoc.lines_with_all_stems(tokens):
            if line_num <= len(sdoc.lines):
                result[(doc_name, line_num)] = _make_posting(doc_name, line_num, sdoc.lines)
    return result


def search_ngram(index: "DocumentSearchIndex", query: str) -> dict:
    """N-gram match — bigram/trigram candidate lines, verify substring."""
    tokens = _tokenize_query(query)
    if not tokens:
        return {}

    stemmed_tokens = [stem(t) for t in tokens]
    result = {}

    for doc_name, sdoc in index.documents.items():
        candidates = sdoc.ngram_index.query(stemmed_tokens)
        if not candidates and len(tokens) == 1:
            candidates = sdoc.lines_with_stem(tokens[0])

        for line_num in candidates:
            if line_num <= len(sdoc.lines):
                result[(doc_name, line_num)] = _make_posting(doc_name, line_num, sdoc.lines)
    return result


def search_meta(
    index: "DocumentSearchIndex",
    query: str,
    synonyms: SynonymIndex | None = None,
) -> dict:
    """Metadata match — search document names, tags, annotations.

    Two passes:
    1. Direct: original query tokens match meta with full weight
    2. Expanded: synonym-expanded tokens (META scope) match meta with synonym weight

    Line-level marks return postings at their actual lines.
    Doc-level marks (e.g. name matches) return at line 0 with descriptive context.
    """
    tokens = _tokenize_query(query)
    if not tokens:
        return {}

    syn = synonyms or DEFAULT_SYNONYMS
    expanded = syn.expand_flat(tokens, scope=ExpansionScope.META)
    expanded_terms = [e.term for e in expanded]
    expanded_weights = {e.term: e.weight for e in expanded}

    result = {}
    for doc_name, sdoc in index.documents.items():
        # Direct match (original tokens, full boost)
        direct_located = sdoc.meta.matches_query_located(tokens)

        # Expanded match (synonym tokens, weighted)
        expanded_located = sdoc.meta.matches_query_located(expanded_terms) if expanded_terms != tokens else []

        # Collect marks by line: None → doc-level (line 0), int → actual line
        by_line: dict[int, list[dict]] = {}
        seen_keys: set[tuple] = set()

        for line_num, m in direct_located:
            mk = (m.key, m.value, line_num)
            if mk not in seen_keys:
                seen_keys.add(mk)
                target = line_num or 0
                by_line.setdefault(target, []).append(
                    {"key": m.key, "value": m.value, "weight": m.weight, "text": m.text}
                )

        for line_num, m in expanded_located:
            mk = (m.key, m.value, line_num)
            if mk not in seen_keys:
                seen_keys.add(mk)
                best_syn_weight = max(
                    (expanded_weights.get(t, 0.5) for t in expanded_terms),
                    default=0.5,
                )
                target = line_num or 0
                by_line.setdefault(target, []).append(
                    {"key": m.key, "value": m.value, "weight": m.weight * best_syn_weight, "text": m.text}
                )

        for line_num, marks in by_line.items():
            if line_num == 0:
                # Doc-level match — use text from best mark as context
                best = max(marks, key=lambda m: m["weight"])
                context = best.get("text", "") or doc_name
                posting = _make_posting(doc_name, 0, sdoc.lines, _meta=marks)
                posting["context"] = context
                result[(doc_name, 0)] = posting
            else:
                # Line-level match — actual annotated line
                context = sdoc.lines[line_num - 1] if line_num <= len(sdoc.lines) else ""
                posting = _make_posting(doc_name, line_num, sdoc.lines, _meta=marks)
                posting["context"] = context
                result[(doc_name, line_num)] = posting

    return result


def search_expanded(
    index: "DocumentSearchIndex",
    query: str,
    synonyms: SynonymIndex | None = None,
) -> dict:
    """Synonym-expanded search — content + meta, scoped expansion.

    1. DOCUMENTS scope: expand tokens, search content indices (union of per-synonym hits)
    2. META scope: expand tokens, search meta indices
    3. Merge with synonym weights as confidence
    """
    tokens = _tokenize_query(query)
    if not tokens:
        return {}

    syn = synonyms or DEFAULT_SYNONYMS
    result: dict = {}

    # Content expansion (DOCUMENTS scope)
    doc_expanded = syn.expand_flat(tokens, scope=ExpansionScope.DOCUMENTS)
    for entry in doc_expanded:
        for doc_name, sdoc in index.documents.items():
            # Try direct word match for this synonym
            for line_num in sdoc.lines_with_word(entry.term):
                if line_num <= len(sdoc.lines):
                    key = (doc_name, line_num)
                    if key not in result or entry.weight > result[key].get("_syn_weight", 0):
                        posting = _make_posting(doc_name, line_num, sdoc.lines)
                        posting["_syn_weight"] = entry.weight
                        posting["_syn_term"] = entry.term
                        result[key] = posting

            # Also try stemmed match
            for line_num in sdoc.lines_with_stem(entry.term):
                if line_num <= len(sdoc.lines):
                    key = (doc_name, line_num)
                    if key not in result:
                        posting = _make_posting(doc_name, line_num, sdoc.lines)
                        posting["_syn_weight"] = entry.weight * WEIGHT_STEMMED
                        posting["_syn_term"] = entry.term
                        result[key] = posting

    # Meta expansion (META scope)
    meta_results = search_meta(index, query, synonyms=syn)
    for key, entry in meta_results.items():
        if key not in result:
            result[key] = entry

    return result


def cascade(index: "DocumentSearchIndex", query: str) -> dict:
    """Try direct → stemmed → n-gram → expanded → meta, return first non-empty."""
    result = search_direct(index, query)
    if result:
        return _boost_meta(index, result, query)
    result = search_stemmed(index, query)
    if result:
        return _boost_meta(index, result, query)
    result = search_ngram(index, query)
    if result:
        return _boost_meta(index, result, query)
    result = search_expanded(index, query)
    if result:
        return _boost_meta(index, result, query)
    return search_meta(index, query)


def merge(index: "DocumentSearchIndex", query: str) -> dict:
    """Run all strategies, merge with confidence weights.

    Each posting gets a ``_confidence`` field reflecting which strategy found it.
    Direct matches rank highest. Meta matches are always included.
    """
    direct = search_direct(index, query)
    stemmed = search_stemmed(index, query)
    ngram = search_ngram(index, query)
    meta = search_meta(index, query)
    expanded = search_expanded(index, query)

    merged: dict = {}

    # Expanded first (lowest priority)
    for key, entry in expanded.items():
        entry["_confidence"] = WEIGHT_EXPANDED
        merged[key] = entry

    # Meta
    for key, entry in meta.items():
        entry["_confidence"] = WEIGHT_META
        merged[key] = entry

    # N-gram
    for key, entry in ngram.items():
        entry["_confidence"] = WEIGHT_NGRAM
        merged[key] = entry

    # Stemmed overwrites n-gram
    for key, entry in stemmed.items():
        entry["_confidence"] = WEIGHT_STEMMED
        merged[key] = entry

    # Direct overwrites everything
    for key, entry in direct.items():
        entry["_confidence"] = WEIGHT_DIRECT
        merged[key] = entry

    return merged


def _boost_meta(index: "DocumentSearchIndex", posting: dict, query: str = "") -> dict:
    """Rank results by BM25 with per-hit boosting (name, meta, synonyms)."""
    from .ranking import rank_postings

    tokens = _tokenize_query(query) if query else []
    return rank_postings(index, posting, tokens)


def search_rrf(index: "DocumentSearchIndex", query: str) -> dict:
    """Run all strategies, fuse with RRF, re-score with BM25.

    Each strategy produces a ranked list. RRF combines ranks so a result
    appearing in multiple strategies ranks higher than one found by only one.
    BM25 with per-hit boosting provides the final _score on top of _rrf.
    """
    from .ranking import rank_postings, rrf

    strategies: list[Callable[["DocumentSearchIndex", str], dict]] = [
        search_direct,
        search_stemmed,
        search_ngram,
        search_expanded,
        search_meta,
    ]
    ranked_lists = [fn(index, query) for fn in strategies]
    ranked_lists = [r for r in ranked_lists if r]

    if not ranked_lists:
        return {}

    fused = rrf(ranked_lists)
    tokens = _tokenize_query(query)
    return rank_postings(index, fused, tokens)


# Strategy dispatch table
STRATEGIES = {
    "direct": search_direct,
    "stemmed": search_stemmed,
    "ngram": search_ngram,
    "meta": search_meta,
    "expanded": search_expanded,
    "cascade": cascade,
    "merge": merge,
    "rrf": search_rrf,
}
