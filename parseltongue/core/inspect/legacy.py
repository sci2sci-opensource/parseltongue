"""Legacy (v1, JSON) corpus caches — detection, inspection, conversion.

A cache written by an earlier parseltongue is *data the operator built*,
often over a long time, and possibly the only copy. Nothing in this
module deletes or rewrites one on its own. The daemon detects the
layout, leaves every file exactly where it is, and reports the choices;
each choice is an explicit `pg cache <choice>` from the operator.

At start a v1 cache is streamed into the current in-memory layout (one
document at a time) and served like any other cache; cache saves are
held so nothing overwrites the v1 files. Choices:

  convert  — write the loaded corpus in the current layout; the v1 files
             are moved aside as ``*.v1.pgz``.
  migrate  — convert, then delete the v1 files.
  rebuild  — move the v1 files aside as ``*.v1.pgz`` and re-walk the
             directory with the current version.
  keep     — leave everything; every start streams the v1 files again.

v1 layout, for reference::

    <key>.idx.pgz  {"directory", "file_hashes", "index": {"documents": {name: {
                       "name", "normalized_text", "position_map", "content_hash",
                       "word_positions", "collapsed_text", "collapsed_to_norm"}},
                     "hashes"}, "indexed_dirs", "file_stats", "dir_mtimes"}
    <key>.six.pgz  {"documents": {name: {"name", "content_hash", "lines",
                       "line_ranges", "word_to_lines", "stem_to_lines",
                       "line_tokens", "ngram_index", "meta"}},
                     "corpus_stems", "corpus_words", "stem_df", "name_stems",
                     "doc_lengths", "avgdl"}
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .pgz import pgz_payload_kind, pgz_stream_to_file

log = logging.getLogger("parseltongue.legacy")

V1_SUFFIX = ".v1.pgz"


@dataclass
class LegacyCache:
    """What was found: the v1 files, untouched, plus what their heads say."""

    key: str
    idx_path: Path | None = None
    six_path: Path | None = None
    directory: str = ""
    documents: int = 0
    indexed_dirs: list[str] = field(default_factory=list)

    @property
    def files(self) -> list[Path]:
        return [p for p in (self.idx_path, self.six_path) if p is not None]

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.files if p.exists())

    def describe(self) -> list[str]:
        """Status lines. The directory comes from the v1 head, so the
        operator sees what a rebuild would walk before choosing."""
        lines = ["index cache: v1 layout (JSON) — loaded in place, files untouched, cache saves held"]
        for p in self.files:
            lines.append(f"  {p.name}  {p.stat().st_size / 1e6:,.0f} MB")
        if self.directory:
            lines.append(f"  {self.documents:,} documents of {self.directory}")
        lines.append("  choose what happens to the files (nothing happens until you do):")
        lines.append("    pg cache convert   write the loaded corpus in the current layout; v1 files kept as *.v1.pgz")
        lines.append("    pg cache migrate   convert, then delete the v1 files")
        lines.append("    pg cache rebuild   re-walk the directory with this version; v1 files kept as *.v1.pgz")
        lines.append("    pg cache keep      leave everything as is (an older parseltongue can still read them)")
        return lines


# ── detection ──


def detect_legacy(idx_path: Path, six_path: Path, key: str) -> LegacyCache | None:
    """Return a LegacyCache if either cache file is in the v1 layout, else None.

    Reads only the envelope and the first bytes of the payload. Never
    modifies anything.
    """
    found = LegacyCache(key=key)
    if idx_path.exists() and pgz_payload_kind(idx_path) == "json":
        found.idx_path = idx_path
    if six_path.exists() and pgz_payload_kind(six_path) == "json":
        found.six_path = six_path
    if not found.files:
        return None
    if found.idx_path is not None:
        try:
            head = _v1_idx_head(found.idx_path)
            found.directory = head.get("directory", "")
            found.documents = head.get("documents", 0)
            found.indexed_dirs = head.get("indexed_dirs", [])
        except Exception as e:  # head is informational; detection stands regardless
            log.warning("legacy cache head unreadable for %s: %s", idx_path.name, e)
    return found


_DIR_RE = re.compile(rb'^\{"directory":"((?:[^"\\]|\\.)*)"')
_HASH_ENTRY_RE = re.compile(rb'"(?:[^"\\]|\\.)*":"[0-9a-f]+"')


def _v1_idx_head(path: Path, limit: int = 64 << 20) -> dict:
    """``directory`` + document count from the first bytes of a v1 idx payload.

    v1 writes ``directory`` first and ``file_hashes`` second, ahead of the
    bulk ``index`` section, so both are recoverable from the head of the
    stream without parsing the file. Streams at most *limit* bytes.
    """
    import zlib

    from .pgz import _PGZ_HEADER

    d = zlib.decompressobj()
    head = bytearray()
    with open(path, "rb") as f:
        f.seek(_PGZ_HEADER.size)
        while len(head) < limit:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            head += d.decompress(chunk)
            if b',"index":' in head:
                break
    out: dict = {}
    m = _DIR_RE.match(head)
    if m:
        out["directory"] = json.loads(b'"' + m.group(1) + b'"')
    fh_start = head.find(b'"file_hashes":{')
    fh_end = head.find(b',"index":', fh_start)
    if fh_start != -1 and fh_end != -1:
        out["documents"] = len(_HASH_ENTRY_RE.findall(head[fh_start:fh_end]))
    return out


# ── moving aside / discarding (explicit choices only) ──


def set_aside(cache: LegacyCache) -> list[Path]:
    """Rename the v1 files to ``*.v1.pgz`` (never overwriting an existing one)."""
    moved = []
    for p in cache.files:
        if not p.exists():
            continue
        target = p.with_name(p.name[: -len(".pgz")] + V1_SUFFIX)
        n = 1
        while target.exists():
            n += 1
            target = p.with_name(p.name[: -len(".pgz")] + f".v1-{n}.pgz")
        p.rename(target)
        moved.append(target)
    return moved


def discard(cache: LegacyCache) -> list[Path]:
    """Delete the v1 files. Only reachable as the second half of
    `pg cache migrate`, after the current layout has been written."""
    removed = []
    for p in cache.files:
        if p.exists():
            p.unlink()
            removed.append(p)
    return removed


# ── streaming conversion ──


def _iter_v1_documents(payload_path: Path, section: bytes) -> Iterator[tuple[str, dict]]:
    """Yield (name, doc_dict) from a decompressed v1 payload on disk, one
    document at a time.

    *section* is the byte string that opens the documents map (e.g.
    ``b'"documents":{'``). The file is memory-mapped; each document value
    is parsed with ``raw_decode`` from its opening brace, so peak memory is
    one document plus the map window, whatever the file size.
    """
    import mmap

    decoder = json.JSONDecoder()
    with open(payload_path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        start = mm.find(section)
        if start == -1:
            return
        pos = start + len(section)
        window = 1 << 20
        while True:
            # Skip separators; stop at the closing brace of the map.
            while mm[pos : pos + 1] in (b",", b" ", b"\n"):
                pos += 1
            if mm[pos : pos + 1] == b"}":
                return
            # Key
            key_end = pos + 1
            while True:
                key_end = mm.find(b'"', key_end)
                if mm[key_end - 1 : key_end] != b"\\":
                    break
                key_end += 1
            name = json.loads(mm[pos : key_end + 1])
            pos = key_end + 1
            assert mm[pos : pos + 1] == b":", "v1 layout: expected ':' after document name"
            pos += 1
            # Value — grow the window until raw_decode sees a complete object.
            size = window
            while True:
                chunk = mm[pos : pos + size].decode("utf-8", errors="surrogateescape")
                try:
                    value, consumed = decoder.raw_decode(chunk)
                    break
                except json.JSONDecodeError:
                    if pos + size >= len(mm):
                        raise
                    size *= 2
            yield name, value
            pos += len(chunk[:consumed].encode("utf-8", errors="surrogateescape"))


def convert_idx(v1_path: Path, original_texts: dict[str, str], config=None, fetch_missing=None):
    """v1 idx payload → (DocumentIndex, head dict with directory/file_hashes/…).

    Documents whose content hash no longer matches *original_texts* are
    re-indexed from the text, as ``DocumentIndex.from_record`` does.
    Documents the v1 head lists but *original_texts* lacks (the text
    history may trail the index) are fetched through
    ``fetch_missing(directory, names) -> {name: text}`` when given — a
    document is never dropped for want of a text lookup.
    """
    from parseltongue.core.quote_verifier.index import DocumentIndex, IndexedDocument, _content_hash
    from parseltongue.core.quote_verifier.posmap import RunMap

    idx = DocumentIndex(config=config)
    with tempfile.NamedTemporaryFile(prefix="pg-v1-idx-", suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        pgz_stream_to_file(v1_path, tmp_path)
        head = _v1_head_dict(tmp_path)
        missing = set(head.get("file_hashes", {})) - set(original_texts)
        if missing and fetch_missing is not None:
            fetched = fetch_missing(head.get("directory", ""), sorted(missing))
            if fetched:
                original_texts = {**original_texts, **fetched}
                log.info("v1 convert: %d document texts fetched from disk (not in text history)", len(fetched))
        for name, d in _iter_v1_documents(tmp_path, b'"documents":{'):
            if name not in original_texts:
                # No text anywhere (not in history, not on disk): the v1
                # entry cannot be verified or rebuilt — report, don't guess.
                log.error("v1 convert: no text for %s; document not carried over", name)
                continue
            original = original_texts[name]
            # Empty files are documents too (v1 indexed them; hash of "").
            if _content_hash(original) != d.get("content_hash"):
                idx.add(name, original)
                continue
            doc = object.__new__(IndexedDocument)
            doc.name = name
            doc.original_text = original
            doc.content_hash = d["content_hash"]
            doc.vocab = idx.vocab
            doc.normalized_text = d["normalized_text"]
            doc.position_map = RunMap.from_seq(d["position_map"])
            wp = d.get("word_positions")
            if wp is None:
                doc._wp_terms, doc._wp_offsets, doc._wp_positions = doc._build_word_index()
            else:
                csr = _csr_from_str_lists(wp, idx.vocab)
                doc._wp_terms, doc._wp_offsets, doc._wp_positions = csr.terms, csr.offsets, csr.values
            doc._collapsed_text = None
            doc._collapsed_to_norm = None
            idx.documents[name] = doc
            idx._hashes[name] = doc.content_hash
    finally:
        tmp_path.unlink(missing_ok=True)
    return idx, head


def convert_six(v1_path: Path, doc_index):
    """v1 six payload → DocumentSearchIndex over *doc_index* (current layout).

    Per-document tables are translated; corpus tables are rebuilt from
    them (as the current loader does), so the corpus sections of the v1
    file are never read.
    """
    from array import array

    from parseltongue.core.quote_verifier.posmap import U32
    from parseltongue.core.search_engine.annotators import DEFAULT_ANNOTATORS
    from parseltongue.core.search_engine.document import SearchDocument
    from parseltongue.core.search_engine.index import DocumentSearchIndex, _build_snapshot
    from parseltongue.core.search_engine.postings import CSR
    from parseltongue.core.search_engine.serialization import deserialize_meta
    from parseltongue.core.search_engine.stemmer import stem
    from parseltongue.core.search_engine.synonyms import DEFAULT_SYNONYMS

    vocab = doc_index.vocab
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
    with tempfile.NamedTemporaryFile(prefix="pg-v1-six-", suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        pgz_stream_to_file(v1_path, tmp_path)
        for name, d in _iter_v1_documents(tmp_path, b'"documents":{'):
            backing = doc_index.documents.get(name)
            lines = d.get("lines") or (backing.original_text.splitlines() if backing else [])
            text = "\n".join(lines)
            line_starts = array(U32, [0])
            pos = text.find("\n")
            while pos != -1:
                line_starts.append(pos + 1)
                pos = text.find("\n", pos + 1)
            words = _csr_from_str_lists(d.get("word_to_lines", {}), vocab)
            stems = _csr_from_str_lists(d.get("stem_to_lines", {}), vocab)
            lt_lines = array(U32)
            lt_offsets = array(U32, [0])
            lt_values = array(U32)
            for ln, tokens in sorted(d.get("line_tokens", []), key=lambda e: e[0]):
                lt_lines.append(ln)
                lt_values.extend(vocab.id(stem(t)) for t in tokens)
                lt_offsets.append(len(lt_values))
            documents[name] = SearchDocument.restore(
                name=name,
                content_hash=d["content_hash"],
                lines=lines,
                vocab=vocab,
                line_starts=line_starts,
                words=CSR(words.terms, words.offsets, words.values),
                stems=CSR(stems.terms, stems.offsets, stems.values),
                line_stems=CSR(lt_lines, lt_offsets, lt_values),
                meta=deserialize_meta(d.get("meta", {})),
                doc=backing,
            )
    finally:
        tmp_path.unlink(missing_ok=True)
    idx._snap = _build_snapshot(documents, DEFAULT_SYNONYMS, vocab)
    return idx


def _csr_from_str_lists(table: dict[str, list[int]], vocab):
    """``{term: [ints]}`` → CSR keyed by vocab id (runs sorted, deduped)."""
    from parseltongue.core.search_engine.postings import CSR

    return CSR.build({vocab.id(term): values for term, values in table.items()})


def _v1_head_dict(payload_path: Path) -> dict:
    """The top-level v1 idx keys other than ``index``: directory, file_hashes,
    indexed_dirs, file_stats, dir_mtimes. Parsed from the head and the tail
    of the payload so the bulk document map is skipped."""
    import mmap

    decoder = json.JSONDecoder()
    out: dict = {}
    with open(payload_path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        head = mm[: min(len(mm), 64 << 20)].decode("utf-8", errors="surrogateescape")
        m = re.match(r'\{"directory":"((?:[^"\\]|\\.)*)"', head)
        if m:
            out["directory"] = json.loads('"' + m.group(1) + '"')
        fh = head.find('"file_hashes":')
        if fh != -1:
            out["file_hashes"], _ = decoder.raw_decode(head, fh + len('"file_hashes":'))
        # Trailing sections come after the index map; scan back from the end.
        tail_len = min(len(mm), 64 << 20)
        tail = mm[len(mm) - tail_len :].decode("utf-8", errors="surrogateescape")
        for key in ("indexed_dirs", "file_stats", "dir_mtimes"):
            k = tail.rfind(f'"{key}":')
            if k != -1:
                try:
                    out[key], _ = decoder.raw_decode(tail, k + len(key) + 3)
                except json.JSONDecodeError:
                    pass
    return out


def workspace_relative(p: Path) -> str:
    try:
        return str(p.relative_to(Path(os.getcwd())))
    except ValueError:
        return str(p)
