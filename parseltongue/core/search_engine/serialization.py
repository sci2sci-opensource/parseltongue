"""Serialize / deserialize SearchDocument and DocumentSearchIndex.

Saves the expensive-to-build line-level indices (word→lines, stem→lines,
per-line stem sequences, metadata) so they survive cache round-trips
without rebuilding from text.

Format is a BlobPGZ record: a JSON head (document names, hashes,
metadata marks, the term list the ids refer to) plus raw ``array('I')``
blobs. Corpus-level tables are not persisted — they are one linear pass
over the per-document id arrays and rebuild in well under the time it
takes to read them.
"""

from __future__ import annotations

from array import array
from collections.abc import Mapping
from typing import TYPE_CHECKING

from parseltongue.core.quote_verifier.vocab import Vocab

if TYPE_CHECKING:
    from parseltongue.core.quote_verifier.index import DocumentIndex

    from .document import SearchDocument
    from .index import DocumentSearchIndex
    from .meta import MetaIndex, MetaMark


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


# ── SearchDocument ──


def serialize_search_document(sdoc: "SearchDocument") -> tuple[dict, dict[str, bytes]]:
    return sdoc.to_record()


def deserialize_search_document(
    meta: dict,
    blobs: Mapping[str, bytes | memoryview],
    vocab: Vocab,
    indexed_doc=None,
    id_remap=None,
) -> "SearchDocument":
    from .document import SearchDocument

    return SearchDocument.from_record(meta, blobs, vocab, indexed_doc, id_remap)


# ── DocumentSearchIndex ──


def serialize_search_index(idx: "DocumentSearchIndex") -> tuple[dict, dict[str, bytes]]:
    """(meta, blobs) for the whole index. Ids are relative to ``idx._vocab``,
    whose term list travels in the head so a later load can re-base them."""
    snap = idx._snap
    docs_meta = []
    blobs: dict[str, bytes] = {}
    for i, (name, sdoc) in enumerate(snap.documents.items()):
        meta, doc_blobs = sdoc.to_record()
        docs_meta.append(meta)
        for key, blob in doc_blobs.items():
            blobs[f"{i}.{key}"] = blob
    from .document import TOKENIZER_VERSION

    return {
        "vocab": list(idx._vocab.terms),
        "tokenizer": TOKENIZER_VERSION,
        "documents": docs_meta,
        "doc_lengths": snap.doc_lengths,
        "avgdl": snap.avgdl,
    }, blobs


def deserialize_search_index(
    meta: dict,
    blobs: Mapping[str, bytes | memoryview],
    doc_index: "DocumentIndex",
) -> "DocumentSearchIndex":
    """Restore a DocumentSearchIndex from :func:`serialize_search_index`
    output + the backing DocumentIndex.

    The cache's term ids are translated onto ``doc_index.vocab`` (the
    live term dictionary), then the corpus tables are rebuilt from the
    per-document arrays.
    """
    from .annotators import DEFAULT_ANNOTATORS
    from .document import SearchDocument
    from .index import DocumentSearchIndex, _build_snapshot
    from .synonyms import DEFAULT_SYNONYMS

    vocab = doc_index.vocab
    cache_terms = meta.get("vocab", [])
    id_remap: array | None = vocab.remap_from(cache_terms)
    # Identity remap → skip the per-document translation entirely.
    if id_remap is not None and all(i == t for i, t in enumerate(id_remap)):
        id_remap = None

    idx = object.__new__(DocumentSearchIndex)
    idx._doc_index = doc_index
    idx._vocab = vocab
    idx._annotators = list(DEFAULT_ANNOTATORS)
    idx._synonyms = DEFAULT_SYNONYMS
    idx._quote_ranges = []
    idx._verifier_documents = {}
    idx._line_callers_cache = None
    idx._line_callers_qr_id = -1

    documents: dict = {}
    backing = doc_index.documents if hasattr(doc_index, "documents") else {}
    for i, doc_meta in enumerate(meta.get("documents", [])):
        name = doc_meta["name"]
        doc_blobs = {key: blobs[f"{i}.{key}"] for key in SearchDocument.BLOB_KEYS}
        documents[name] = SearchDocument.from_record(doc_meta, doc_blobs, vocab, backing.get(name), id_remap)

    idx._snap = _build_snapshot(documents, DEFAULT_SYNONYMS, vocab)
    return idx
