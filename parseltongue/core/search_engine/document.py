"""SearchDocument — line-level search index wrapping IndexedDocument.

Adds what IndexedDocument doesn't have:
- Pre-split lines (computed once)
- word → line numbers mapping (from existing word_positions + position_map)
- Stemmed word → line numbers mapping
- Per-line stem sequences (phrase / n-gram verification)
- Metadata index (token, word, line, doc level marks with boost)

All built from IndexedDocument's already-normalized text. No re-normalization.

Every posting table is an ``array('I')`` CSR keyed by term id (see
``postings``); the term dictionary is the index-wide ``Vocab``.
"""

from __future__ import annotations

import re as _re
from array import array
from collections import defaultdict
from typing import TYPE_CHECKING

from parseltongue.core.quote_verifier.posmap import U32
from parseltongue.core.quote_verifier.vocab import Vocab

from .meta import MetaIndex, index_doc_name
from .postings import CSR, EMPTY, LineSet, TermLines
from .stemmer import stem

_COMPOUND_SPLIT = _re.compile(r"[._\-/]+")
_UNIT_SPLIT = _re.compile(r"[./]+")  # path / module segments
_PART_SPLIT = _re.compile(r"[_\-]+")  # snake / kebab parts within a segment
_CAMEL_SPLIT = _re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SIGILS = "@#$%&*()[]{}<>!?,;:'\"`~|\\^=+"

#: Bump when split_compound changes what an index stores per word. A .six
#: cache built by another version still loads, and `pg status` says it
#: was tokenized differently — queries for parts only this version emits
#: will miss until `pg reindex --force`.
TOKENIZER_VERSION = 2


def split_compound(word: str) -> list[str]:
    """Sub-tokens of an identifier-like word, or [] if it has none.

    Two levels, both emitted: the *units* between ``/`` and ``.`` (path and
    module segments — ``widgets_v2``, ``inference_service``), and within
    each unit the snake/kebab/camelCase *parts*. So
    ``src/widgets_v2/AssetEntry.tsx`` → ``src``, ``widgets_v2``,
    ``widgets``, ``v2``, ``assetentry``, ``asset``, ``entry``, ``tsx``;
    ``app.services.inference_service`` → ``app``, ``services``,
    ``inference_service``, ``inference``, ``service``. Leading/trailing
    sigils (``@scope``, ``(foo``) are dropped. Everything is lowercased;
    *word* may carry original case for the camel split.
    """
    lowered = word.lower()
    seen: set[str] = set()
    out: list[str] = []

    def _emit(token: str) -> None:
        token = token.strip(_SIGILS).lower()
        if token and token != lowered and token not in seen:
            seen.add(token)
            out.append(token)

    for unit in _UNIT_SPLIT.split(word):
        if not unit:
            continue
        _emit(unit)
        parts = [p for p in _PART_SPLIT.split(unit) if p]
        camel_any = any(len(_CAMEL_SPLIT.split(p)) > 1 for p in parts)
        if len(parts) > 1 or camel_any:
            for p in parts:
                _emit(p)
                for c in _CAMEL_SPLIT.split(p):
                    _emit(c)
    return out


if TYPE_CHECKING:
    from parseltongue.core.quote_verifier.index import IndexedDocument


class SearchDocument:
    """Line-level search index for a single document.

    Wraps an IndexedDocument and adds line-oriented indices
    for fast lookup by word, stemmed word, phrase, and metadata.
    """

    __slots__ = (
        "name",
        "doc",
        "vocab",
        "lines",
        "meta",
        "_content_hash",
        "_line_starts",
        "_words",
        "_stems",
        "_line_stems",
        "_match_starts",
        "_match_ends",
        "_nonbmp",
    )

    doc: "IndexedDocument"
    _match_starts: CSR | None
    _match_ends: array | None
    _nonbmp: array | None

    def __init__(self, doc: "IndexedDocument", vocab: Vocab | None = None):
        self.name = doc.name
        self.doc = doc
        self.vocab = vocab if vocab is not None else doc.vocab
        self._content_hash = doc.content_hash
        self.lines: list[str] = doc.original_text.splitlines()

        # Metadata index — token/word/line/doc level marks
        self.meta = MetaIndex()
        index_doc_name(self.meta, doc.name)

        self._build_line_indices()

    # ── construction ──

    @classmethod
    def restore(
        cls,
        name: str,
        content_hash: str,
        lines: list[str],
        vocab: Vocab,
        line_starts: array,
        words: CSR,
        stems: CSR,
        line_stems: CSR,
        meta: MetaIndex,
        doc: "IndexedDocument | None",
        match_starts: CSR | None = None,
        match_ends: array | None = None,
        nonbmp: array | None = None,
    ) -> "SearchDocument":
        """Assemble from persisted parts — no indexing work."""
        sdoc = object.__new__(cls)
        sdoc.name = name
        sdoc.doc = doc  # type: ignore[assignment]
        sdoc.vocab = vocab
        sdoc._content_hash = content_hash
        sdoc.lines = lines
        sdoc.meta = meta
        sdoc._line_starts = line_starts
        sdoc._words = words
        sdoc._stems = stems
        sdoc._line_stems = line_stems
        sdoc._match_starts = match_starts
        sdoc._match_ends = match_ends
        sdoc._nonbmp = nonbmp
        return sdoc

    def _build_line_indices(self):
        """Build word→lines, stem→lines and per-line stem sequences from
        normalized text + position_map."""
        doc = self.doc
        norm_text = doc.normalized_text
        pos_map = doc.position_map
        orig_text = doc.original_text
        vocab_id = self.vocab.id

        # Line start offsets in original text.
        line_starts = array(U32, [0])
        pos = orig_text.find("\n")
        while pos != -1:
            line_starts.append(pos + 1)
            pos = orig_text.find("\n", pos + 1)
        self._line_starts = line_starts
        n_lines = len(line_starts)

        def _char_to_line(orig_pos: int) -> int:
            # Binary search for line number
            lo, hi = 0, n_lines - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if line_starts[mid] <= orig_pos:
                    lo = mid
                else:
                    hi = mid - 1
            return lo + 1  # 1-based

        word_lines: dict[int, list[int]] = defaultdict(list)
        stem_lines: dict[int, list[int]] = defaultdict(list)
        per_line_stems: dict[int, list[int]] = defaultdict(list)
        match_spans: dict[int, list[tuple[int, int]]] = defaultdict(list)
        self._nonbmp = array(U32, (m.start() for m in _re.finditer(r"[\U00010000-\U0010ffff]", orig_text)))
        pm_len = len(pos_map)

        # Walk normalized text, extract words, map each to original line
        i = 0
        n = len(norm_text)
        while i < n:
            while i < n and norm_text[i] == " ":
                i += 1
            if i >= n:
                break
            start = i
            while i < n and norm_text[i] != " ":
                i += 1
            word = norm_text[start:i]
            if not word:
                continue

            # Map back to original position → line number
            orig_pos = pos_map[start] if start < pm_len else 0
            line_num = _char_to_line(orig_pos)

            word_lines[vocab_id(word)].append(line_num)
            stemmed_id = vocab_id(stem(word))
            stem_lines[stemmed_id].append(line_num)
            orig_end = pos_map[i - 1] + 1
            match_spans[stemmed_id].append((orig_pos, orig_end))

            # Sub-tokens of identifier-like words: "systems.operations_v2" →
            # systems, operations, v2; "src/widgets_v2/AssetEntry" → src,
            # widgets_v2, widgets, v2, asset, entry. The camel split needs
            # the original casing, which normalization dropped — take the
            # word's span in the original text through the position map.
            end = i - 1
            if end < pm_len and len(word) > 1:
                cased = orig_text[orig_pos : pos_map[end] + 1]
                if len(cased) != len(word):
                    cased = word
            else:
                cased = word
            for part in split_compound(cased):
                word_lines[vocab_id(part)].append(line_num)
                part_id = vocab_id(stem(part))
                stem_lines[part_id].append(line_num)
                # Resolve compound ranges once, while building the index.
                original = orig_text[orig_pos:orig_end]
                for match in _re.finditer(_re.escape(part), original, _re.I):
                    match_spans[part_id].append((orig_pos + match.start(), orig_pos + match.end()))

            per_line_stems[line_num].append(stemmed_id)

        terms = array(U32, sorted(match_spans))
        offsets, starts, ends = array(U32, [0]), array(U32), array(U32)
        for tid in terms:
            for a, b in sorted(set(match_spans[tid])):
                starts.append(a)
                ends.append(b)
            offsets.append(len(starts))
        self._match_starts = CSR(terms, offsets, starts)
        self._match_ends = ends
        self._words = CSR.build(word_lines)
        self._stems = CSR.build(stem_lines)
        # Line → stem sequence, in token order (not deduped, not sorted).
        lt_lines = array(U32, sorted(per_line_stems))
        lt_offsets = array(U32, [0])
        lt_values = array(U32)
        for ln in lt_lines:
            lt_values.extend(per_line_stems[ln])
            lt_offsets.append(len(lt_values))
        self._line_stems = CSR(lt_lines, lt_offsets, lt_values)

    # ── mapping views (dict[str, set[int]] compatible) ──

    @property
    def word_to_lines(self) -> TermLines:
        return TermLines(self._words, self.vocab)

    @property
    def stem_to_lines(self) -> TermLines:
        return TermLines(self._stems, self.vocab)

    @property
    def line_ranges(self) -> list[tuple[int, int]]:
        """(start_char, end_char) per line in the original text; index 0 = line 1."""
        starts = self._line_starts
        text_len = len(self.doc.original_text) if self.doc is not None else (starts[-1] if starts else 0)
        out = []
        for idx in range(len(starts)):
            start = starts[idx]
            end = (starts[idx + 1] - 2) if idx + 1 < len(starts) else text_len - 1
            out.append((start, max(start, end)))
        return out

    # ── queries ──

    def lines_with_word(self, word: str) -> LineSet:
        """Line numbers (1-based) containing this normalized word."""
        return self.word_to_lines.get(word, EMPTY)

    def lines_with_stem(self, word: str) -> LineSet:
        """Line numbers containing any word that stems to the same root."""
        return self.stem_to_lines.get(stem(word), EMPTY)

    def lines_with_all_words(self, words: list[str]) -> LineSet:
        """Line numbers containing ALL given words (intersection)."""
        if not words:
            return EMPTY
        result = self.lines_with_word(words[0])
        for w in words[1:]:
            result = result & self.lines_with_word(w)
            if not result:
                break
        return result

    def lines_with_all_stems(self, words: list[str]) -> LineSet:
        """Line numbers containing stems of ALL given words."""
        if not words:
            return EMPTY
        result = self.lines_with_stem(words[0])
        for w in words[1:]:
            result = result & self.lines_with_stem(w)
            if not result:
                break
        return result

    def lines_with_phrase(self, stems: list[str]) -> LineSet:
        """Lines where the given stems occur consecutively, in order.

        Candidate lines come from intersecting the per-stem postings; each
        candidate's stem sequence is then scanned for the exact run. This is
        what the bigram/trigram tables used to approximate — derived from
        positions instead of stored.
        """
        if len(stems) < 2:
            return EMPTY
        ids = []
        for s in stems:
            tid = self.vocab.lookup(s)
            if tid is None:
                return EMPTY
            ids.append(tid)
        cand: LineSet | None = None
        for tid in ids:
            ls = self.stem_to_lines.by_id(tid)
            if ls is None:
                return EMPTY
            cand = ls if cand is None else cand & ls
            if not cand:
                return EMPTY
        assert cand is not None
        first = ids[0]
        k = len(ids)
        hits = array(U32)
        seq_tab = self._line_stems
        for ln in cand:
            slot = seq_tab.slot(ln)
            if slot < 0:
                continue
            seq = seq_tab.run(slot)
            n = len(seq)
            for j in range(n - k + 1):
                if seq[j] == first and list(seq[j : j + k]) == ids:
                    hits.append(ln)
                    break
        return LineSet(hits)

    # ── persistence ──

    def to_record(self) -> tuple[dict, dict[str, bytes]]:
        from .serialization import serialize_meta

        meta = {
            "name": self.name,
            "content_hash": self._content_hash,
            "meta": serialize_meta(self.meta),
        }
        blobs = {
            "tx": "\n".join(self.lines).encode("utf-8"),
            "ls": self._line_starts.tobytes(),
        }
        blobs.update(self._words.to_blobs("wl"))
        blobs.update(self._stems.to_blobs("sl"))
        blobs.update(self._line_stems.to_blobs("lt"))
        if self._match_starts is not None:
            assert self._match_ends is not None and self._nonbmp is not None
            blobs.update(self._match_starts.to_blobs("hp"))
            blobs["he"] = self._match_ends.tobytes()
            blobs["nb"] = self._nonbmp.tobytes()
        return meta, blobs

    BLOB_KEYS = ("tx", "ls", "wl.t", "wl.o", "wl.v", "sl.t", "sl.o", "sl.v", "lt.t", "lt.o", "lt.v")

    POSITION_BLOB_KEYS = ("hp.t", "hp.o", "hp.v", "he", "nb")

    @classmethod
    def from_record(
        cls,
        meta: dict,
        blobs,
        vocab: Vocab,
        doc: "IndexedDocument | None",
        id_remap: array | None = None,
    ) -> "SearchDocument":
        from .serialization import deserialize_meta

        line_starts = array(U32)
        line_starts.frombytes(blobs["ls"])
        words = CSR.from_blobs(blobs, "wl")
        stems = CSR.from_blobs(blobs, "sl")
        line_stems = CSR.from_blobs(blobs, "lt")
        match_starts = None
        match_ends = nonbmp = None
        if "hp.t" in blobs:
            match_starts = CSR.from_blobs(blobs, "hp")
            match_ends, nonbmp = array(U32), array(U32)
            match_ends.frombytes(blobs["he"])
            nonbmp.frombytes(blobs["nb"])
            if id_remap is not None:
                # Reorder both parallel arrays by the same term permutation.
                end_table = CSR(match_starts.terms, match_starts.offsets, match_ends).remapped(id_remap)
                match_starts = match_starts.remapped(id_remap)
                match_ends = end_table.values
        if id_remap is not None:
            words = words.remapped(id_remap)
            stems = stems.remapped(id_remap)
            # line_stems is keyed by line number; only its values are term ids.
            line_stems = CSR(line_stems.terms, line_stems.offsets, array(U32, (id_remap[t] for t in line_stems.values)))
        if doc is not None:
            lines = doc.original_text.splitlines()
        else:
            lines = bytes(blobs["tx"]).decode("utf-8").split("\n")
        return cls.restore(
            name=meta["name"],
            content_hash=meta["content_hash"],
            lines=lines,
            vocab=vocab,
            line_starts=line_starts,
            words=words,
            stems=stems,
            line_stems=line_stems,
            meta=deserialize_meta(meta.get("meta", {})),
            doc=doc,
            match_starts=match_starts,
            match_ends=match_ends,
            nonbmp=nonbmp,
        )
