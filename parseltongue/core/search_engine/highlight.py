"""Search-owned character ranges, using stored normalization position maps.

Offsets are half-open UTF-16 code-unit offsets into the returned context, so
browser clients can slice them directly. Terms retain precise matches; passages
are minimal windows containing the matched term groups, regardless of order.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections import Counter

from .stemmer import stem
from .strategy import _tokenize_query


def ranges(text: str, hits: list[tuple[int, int, str]], *, nonbmp=None, origin: int = 0) -> list[dict]:
    hits = sorted(set(hits))
    if not hits:
        return []
    spans = {(a, b, "term") for a, b, _ in hits}
    groups = {g for _, _, g in hits}
    if len(groups) > 1:
        counts: Counter = Counter()
        left = 0
        for right, (_, end, group) in enumerate(hits):
            counts[group] += 1
            while len(counts) == len(groups):
                while counts[hits[left][2]] > 1:
                    counts[hits[left][2]] -= 1
                    left += 1
                start, _, first = hits[left]
                # Keep separate passages readable instead of shading a whole
                # long tool record between unrelated occurrences.
                if end - start <= 320:
                    spans.add((start, end, "passage"))
                counts[first] -= 1
                if not counts[first]:
                    del counts[first]
                left += 1
    # Only non-BMP characters add a UTF-16 code unit. Indexed source text
    # supplies this sparse table; decoded display text computes it once.
    if nonbmp is None:
        nonbmp = [m.start() for m in re.finditer(r"[\U00010000-\U0010ffff]", text)]
    base = bisect_left(nonbmp, origin)

    def offset(pos):
        return pos + bisect_left(nonbmp, origin + pos) - base

    return [
        {"start": offset(a), "end": offset(b), "kind": kind} for a, b, kind in sorted(spans) if 0 <= a < b <= len(text)
    ]


def highlight_display(text: str, matched_terms: list[str]) -> list[dict]:
    """Remap already-matched source lexemes after a client decodes tool JSON.

    This does not reinterpret a query: its input is actual indexed matches.
    """
    hits: list[tuple[int, int, str]] = []
    for term in set(matched_terms):
        if term:
            hits.extend((m.start(), m.end(), term.lower()) for m in re.finditer(re.escape(term), text, re.I))
    return ranges(text, hits)


def highlight_entry(index, entry: dict) -> dict:
    text = entry.get("context", "")
    sdoc = index.documents.get(entry["document"])
    queries = entry.get("_match_queries", ())
    hits: list[tuple[int, int, str]] = []
    nonbmp, origin = None, 0
    if sdoc is not None and sdoc._match_starts is not None:
        line = entry["line"]
        if 1 <= line <= len(sdoc.lines) and text == sdoc.lines[line - 1]:
            start = sdoc._line_starts[line - 1]
            end = start + len(text)
            nonbmp, origin = sdoc._nonbmp, start
            wanted: dict[str, str] = {}
            corpus = index._snap.corpus_stems
            for query in queries:
                for token in _tokenize_query(query):
                    token_group = stem(token)
                    wanted[token_group] = token_group
                    tid = index._vocab.lookup(token_group)
                    if tid is not None:
                        for source in corpus.syn_sources.get(tid, ()):
                            wanted[index._vocab.term(source)] = token_group
            table = sdoc._match_starts
            ends = sdoc._match_ends
            for token, group in wanted.items():
                tid = index._vocab.lookup(token)
                if tid is None:
                    continue
                slot = bisect_left(table.terms, tid)
                if slot == len(table.terms) or table.terms[slot] != tid:
                    continue
                lo, hi = table.offsets[slot], table.offsets[slot + 1]
                first = bisect_left(table.values, start, lo, hi)
                last = bisect_left(table.values, end, first, hi)
                hits.extend((table.values[k] - start, ends[k] - start, group) for k in range(first, last))
    for pattern in entry.get("_match_regex", ()):
        hits.extend((m.start(), m.end(), pattern) for m in re.finditer(pattern, text) if m.end() > m.start())
    result = {k: v for k, v in entry.items() if not k.startswith("_match_")}
    result["highlights"] = ranges(text, hits, nonbmp=nonbmp, origin=origin)
    result["matched_terms"] = sorted({text[a:b] for a, b, _ in hits})
    return result


def merge_matches(left: dict, right: dict) -> dict:
    result = dict(left)
    for key in ("_match_queries", "_match_regex"):
        result[key] = tuple(dict.fromkeys((*left.get(key, ()), *right.get(key, ()))))
    return result
