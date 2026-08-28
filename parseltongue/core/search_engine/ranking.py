"""BM25 ranking for search results.

Document-level BM25 with meta boost overlay. Each posting entry gets a
``_score`` field combining:
    BM25(query, doc) × meta_boost(query, doc) × Π(rule penalties)

Standard BM25 parameters: k1=1.2, b=0.75.

Ranking rules are predicate-based multipliers applied after BM25 scoring.
Each rule tests the document name and applies a penalty (< 1.0) when matched.
Rules are composable — all matching penalties multiply together.
Pass ``rules=[]`` to ``rank_postings`` to disable penalties entirely.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .stemmer import stem
from .synonyms import DEFAULT_SYNONYMS, ExpansionScope

if TYPE_CHECKING:
    from .index import DocumentSearchIndex


# ── Ranking rules ──


@dataclass(frozen=True, slots=True)
class RankingRule:
    """A named predicate that penalizes matching documents.

    predicate: takes doc_name, returns True if penalty applies.
    multiplier: score is multiplied by this (< 1.0 = penalty).
    suppressed_by: query terms that disable this rule (e.g. "test" suppresses test_file penalty).
    """

    name: str
    predicate: Callable[[str], bool]
    multiplier: float
    suppressed_by: frozenset[str] = frozenset()


def _is_test_file(doc_name: str) -> bool:
    """True for test files: test_*.py, *_test.py, tests/, etc."""
    low = doc_name.lower()
    base = os.path.basename(low)
    return (
        base.startswith("test_")
        or base.endswith("_test.py")
        or "/tests/" in low
        or "/test/" in low
        or low.startswith("tests/")
        or low.startswith("test/")
    )


def _is_init_file(doc_name: str) -> bool:
    return os.path.basename(doc_name) == "__init__.py"


def _is_generated(doc_name: str) -> bool:
    low = doc_name.lower()
    return "generated" in low or "autogen" in low


def _is_vendor(doc_name: str) -> bool:
    low = doc_name.lower()
    return "/vendor/" in low or "/node_modules/" in low


def _is_config(doc_name: str) -> bool:
    return any(doc_name.endswith(ext) for ext in (".cfg", ".ini", ".toml", ".yaml", ".yml"))


def _is_deep(doc_name: str) -> bool:
    return doc_name.count("/") > 5


# Default rules — tests penalized hardest so real code always surfaces first.
# suppressed_by: if any query token matches, the rule is skipped (user is looking for that kind of file).
DEFAULT_RULES: list[RankingRule] = [
    RankingRule("test_file", _is_test_file, 0.25, frozenset({"test", "tests", "testing", "unittest", "pytest"})),
    RankingRule("init_file", _is_init_file, 0.7, frozenset({"init", "__init__"})),
    RankingRule("generated", _is_generated, 0.3, frozenset({"generated", "autogen", "codegen"})),
    RankingRule("vendor", _is_vendor, 0.2, frozenset({"vendor", "node_modules"})),
    RankingRule("config", _is_config, 0.8, frozenset({"config", "cfg", "ini", "toml", "yaml", "yml", "settings"})),
    RankingRule("deep_nesting", _is_deep, 0.9),
]


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
    # Grab snapshot once — consistent view for the entire scoring pass.
    snap = index._snap
    documents = snap.documents

    N = len(documents)
    if N == 0:
        return {}

    # Pre-computed in snapshot — no per-query scan needed.
    doc_lengths = snap.doc_lengths
    avgdl = snap.avgdl
    stem_df = snap.stem_df
    corpus_stems = snap.corpus_stems
    doc_name_stems = snap.name_stems or {name: _name_tokens(name) for name in documents}

    # Expand each query token via synonyms
    expanded_stems: list[list[tuple[str, float]]] = []
    for t in query_tokens:
        synonyms = DEFAULT_SYNONYMS.expand(t, scope=ExpansionScope.UNIVERSAL)
        expanded_stems.append([(stem(e.term), e.weight) for e in synonyms])

    # Meta boost — computed lazily per candidate, not all docs upfront.
    doc_meta_boost: dict[str, float] = {}

    def _meta_boost(name: str) -> float:
        if name not in doc_meta_boost:
            sdoc = documents.get(name)
            if sdoc is not None:
                matching = sdoc.meta.matches_query(query_tokens)
                doc_meta_boost[name] = sum(m.weight for m in matching) if matching else 1.0
            else:
                doc_meta_boost[name] = 1.0
        return doc_meta_boost[name]

    # Reverse index: stem → set of doc names whose filename contains that stem
    name_stem_to_docs: dict[str, set[str]] = {}
    for name, ns in doc_name_stems.items():
        for s in ns:
            if s not in name_stem_to_docs:
                name_stem_to_docs[s] = set()
            name_stem_to_docs[s].add(name)

    scores: dict[str, float] = {}

    for term_group in expanded_stems:
        # Collect candidate docs from inverted index — only docs containing ≥1 variant
        candidates: dict[str, list[tuple[str, float]]] = {}
        for t, syn_weight in term_group:
            # Content hits via inverted index
            for name in corpus_stems.doc_names_for(t):
                if name not in candidates:
                    candidates[name] = []
                candidates[name].append((t, syn_weight))
            # Name hits via reverse name-stem index
            for name in name_stem_to_docs.get(t, ()):
                if name not in candidates:
                    candidates[name] = []
                    candidates[name].append((t, syn_weight))

        # Score only candidate docs
        for name, hits in candidates.items():
            sdoc = documents.get(name)
            if sdoc is None:
                continue
            dl = doc_lengths.get(name, 0)
            best_contribution = 0.0

            for t, syn_weight in hits:
                tf = len(sdoc.stem_to_lines.get(t, set()))
                if t in doc_name_stems.get(name, set()):
                    tf += 10
                if tf == 0:
                    continue

                df = stem_df.get(t, 0)
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1.0)

                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * dl / avgdl)

                hit_boost = syn_weight * _meta_boost(name)
                contribution = idf * numerator / denominator * hit_boost
                best_contribution = max(best_contribution, contribution)

            if best_contribution > 0:
                scores[name] = scores.get(name, 0.0) + best_contribution

    return scores


def line_score(
    index: "DocumentSearchIndex",
    doc_name: str,
    line_num: int,
    query_tokens: list[str],
    _snap=None,
) -> float:
    """Score a single line by how many query terms (or synonyms) it contains.

    Returns a 0–1 ratio: matched_terms / total_query_terms.
    Each term uses best synonym match (weighted).
    """
    docs = (_snap or index._snap).documents
    sdoc = docs.get(doc_name)
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


def _filter_rules(rules: list[RankingRule], query_tokens: list[str]) -> list[RankingRule]:
    """Remove rules suppressed by query terms."""
    if not query_tokens:
        return rules
    query_lower = {t.lower() for t in query_tokens}
    return [r for r in rules if not (r.suppressed_by and r.suppressed_by & query_lower)]


def _apply_rules(doc_name: str, rules: list[RankingRule]) -> float:
    """Compute combined penalty multiplier for a document."""
    penalty = 1.0
    for rule in rules:
        if rule.predicate(doc_name):
            penalty *= rule.multiplier
    return penalty


def rank_postings(
    index: "DocumentSearchIndex",
    posting: dict,
    query_tokens: list[str],
    *,
    rules: list[RankingRule] | None = None,
) -> dict:
    """Score and sort by doc-level BM25 × line-level term coverage × rule penalties.

    _score = bm25(doc) × line_score(line) × Π(matching rule multipliers).
    Rules whose ``suppressed_by`` terms appear in the query are skipped —
    if the user searches for "test", test files aren't penalized.
    Pass ``rules=[]`` to disable penalties. Default: ``DEFAULT_RULES``.
    """
    if not posting:
        return posting

    snap = index._snap  # consistent view for entire scoring pass
    active_rules = _filter_rules(DEFAULT_RULES if rules is None else rules, query_tokens)
    doc_scores = bm25_score(index, query_tokens)

    # Cache penalty per document (many lines share the same doc)
    penalty_cache: dict[str, float] = {}

    for (doc_name, line_num), entry in posting.items():
        bm25 = doc_scores.get(doc_name, 0.0)
        ls = line_score(index, doc_name, line_num, query_tokens, _snap=snap)
        raw = bm25 * ls if ls > 0 else bm25 * 0.01

        if active_rules:
            if doc_name not in penalty_cache:
                penalty_cache[doc_name] = _apply_rules(doc_name, active_rules)
            raw *= penalty_cache[doc_name]

        # Floor: strategy already validated this hit — BM25 reorders, never erases.
        entry["_score"] = round(max(raw, 1e-4), 4)

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
