"""Serialize / deserialize SearchDocument and DocumentSearchIndex.

Saves the expensive-to-build line-level indices (word→lines, stem→lines,
n-grams, metadata, corpus indices) so they survive cache round-trips
without rebuilding from text.

Format is JSON-friendly dicts with sets → sorted lists for determinism.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .document import SearchDocument
    from .index import DocumentSearchIndex
    from .meta import MetaIndex, MetaMark
    from .ngrams import NGramIndex


# ── MetaMark ──

def _serialize_mark(m: "MetaMark") -> dict:
    d: dict = {"key": m.key, "value": m.value}
    if m.weight != 1.0:
        d["weight"] = m.weight
    if m.text:
        d["text"] = m.text
    return d


def _deserialize_mark(d: dict) -> "MetaMark":
    from .meta import MetaMark
    return MetaMark(
        key=d["key"],
        value=d["value"],
        weight=d.get("weight", 1.0),
        text=d.get("text", ""),
    )


# ── MetaIndex ──

def serialize_meta(meta: "MetaIndex") -> dict:
    return {
        "token_meta": {str(k): [_serialize_mark(m) for m in v] for k, v in meta.token_meta.items()},
        "word_meta": {k: [_serialize_mark(m) for m in v] for k, v in meta.word_meta.items()},
        "line_meta": {str(k): [_serialize_mark(m) for m in v] for k, v in meta.line_meta.items()},
        "doc_meta": [_serialize_mark(m) for m in meta.doc_meta],
    }


def deserialize_meta(d: dict) -> "MetaIndex":
    from .meta import MetaIndex
    meta = MetaIndex()
    for k, marks in d.get("token_meta", {}).items():
        meta.token_meta[int(k)] = [_deserialize_mark(m) for m in marks]
    for k, marks in d.get("word_meta", {}).items():
        meta.word_meta[k] = [_deserialize_mark(m) for m in marks]
        # Rebuild _stem_meta
        from .stemmer import stem
        for m in meta.word_meta[k]:
            meta._stem_meta.setdefault(stem(k), []).append(m)
    for k, marks in d.get("line_meta", {}).items():
        meta.line_meta[int(k)] = [_deserialize_mark(m) for m in marks]
    meta.doc_meta = [_deserialize_mark(m) for m in d.get("doc_meta", [])]
    return meta


# ── NGramIndex ──

def serialize_ngrams(ng: "NGramIndex") -> dict:
    return {
        "bigrams": {f"{a}\x00{b}": sorted(lines) for (a, b), lines in ng.bigrams.items()},
        "trigrams": {f"{a}\x00{b}\x00{c}": sorted(lines) for (a, b, c), lines in ng.trigrams.items()},
    }


def deserialize_ngrams(d: dict) -> "NGramIndex":
    from .ngrams import NGramIndex
    ng = NGramIndex()
    for key, lines in d.get("bigrams", {}).items():
        parts = key.split("\x00")
        ng.bigrams[(parts[0], parts[1])] = set(lines)
    for key, lines in d.get("trigrams", {}).items():
        parts = key.split("\x00")
        ng.trigrams[(parts[0], parts[1], parts[2])] = set(lines)
    return ng


# ── SearchDocument ──

def _set_to_list(s: set) -> list:
    return sorted(s)


def _lines_dict_to_json(d: dict[str, set[int]]) -> dict[str, list[int]]:
    return {k: sorted(v) for k, v in d.items()}


def _lines_dict_from_json(d: dict[str, list[int]]) -> dict[str, set[int]]:
    return {k: set(v) for k, v in d.items()}


def serialize_search_document(sdoc: "SearchDocument") -> dict:
    return {
        "name": sdoc.name,
        "content_hash": sdoc._content_hash,
        "lines": sdoc.lines,
        "line_ranges": sdoc.line_ranges,
        "word_to_lines": _lines_dict_to_json(sdoc.word_to_lines),
        "stem_to_lines": _lines_dict_to_json(sdoc.stem_to_lines),
        "line_tokens": [[ln, tokens] for ln, tokens in sdoc._line_tokens],
        "ngram_index": serialize_ngrams(sdoc.ngram_index),
        "meta": serialize_meta(sdoc.meta),
    }


def deserialize_search_document(d: dict, indexed_doc: "object | None" = None) -> "SearchDocument":
    """Restore a SearchDocument from serialized data.

    If indexed_doc is provided, it's used as the backing doc reference.
    Otherwise a stub is created with just the name.
    """
    from .document import SearchDocument
    from .meta import MetaIndex
    from .ngrams import NGramIndex

    # Create without calling __init__ — we'll set everything manually
    sdoc = object.__new__(SearchDocument)
    sdoc.name = d["name"]
    sdoc._content_hash = d["content_hash"]
    sdoc.lines = d["lines"]
    sdoc.line_ranges = [tuple(r) for r in d["line_ranges"]]
    sdoc.word_to_lines = _lines_dict_from_json(d["word_to_lines"])
    sdoc.stem_to_lines = _lines_dict_from_json(d["stem_to_lines"])
    sdoc._line_tokens = [(ln, tokens) for ln, tokens in d["line_tokens"]]
    sdoc.ngram_index = deserialize_ngrams(d["ngram_index"])
    sdoc.meta = deserialize_meta(d["meta"])
    sdoc.doc = indexed_doc
    return sdoc


# ── DocumentSearchIndex ──

def _corpus_to_json(corpus: dict[str, dict[str, set[int]]]) -> dict[str, dict[str, list[int]]]:
    return {stem: {doc: sorted(lines) for doc, lines in docs.items()} for stem, docs in corpus.items()}


def _corpus_from_json(d: dict[str, dict[str, list[int]]]) -> dict[str, dict[str, set[int]]]:
    return {stem: {doc: set(lines) for doc, lines in docs.items()} for stem, docs in d.items()}


def serialize_search_index(idx: "DocumentSearchIndex") -> dict:
    return {
        "documents": {name: serialize_search_document(sdoc) for name, sdoc in idx.documents.items()},
        "corpus_stems": _corpus_to_json(idx._corpus_stems),
        "corpus_words": _corpus_to_json(idx._corpus_words),
        "stem_df": idx._stem_df,
        "name_stems": {k: sorted(v) for k, v in idx._name_stems.items()},
    }


def deserialize_search_index(d: dict, doc_index: "object") -> "DocumentSearchIndex":
    """Restore a DocumentSearchIndex from serialized data + backing DocumentIndex."""
    from .annotators import DEFAULT_ANNOTATORS
    from .index import DocumentSearchIndex
    from .synonyms import DEFAULT_SYNONYMS

    idx = object.__new__(DocumentSearchIndex)
    idx._doc_index = doc_index
    idx._annotators = list(DEFAULT_ANNOTATORS)
    idx._synonyms = DEFAULT_SYNONYMS

    # Restore documents
    idx.documents = {}
    for name, sdoc_data in d.get("documents", {}).items():
        backing_doc = doc_index.documents.get(name) if hasattr(doc_index, 'documents') else None
        idx.documents[name] = deserialize_search_document(sdoc_data, backing_doc)

    # Restore corpus indices
    idx._corpus_stems = _corpus_from_json(d.get("corpus_stems", {}))
    idx._corpus_words = _corpus_from_json(d.get("corpus_words", {}))
    idx._stem_df = d.get("stem_df", {})
    idx._name_stems = {k: set(v) for k, v in d.get("name_stems", {}).items()}

    return idx
