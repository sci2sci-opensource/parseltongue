"""PGZ disk formats — envelope, JsonPGZ, OrdinalPGZ, and LayeredTexts.



PGZ envelope — shared by JsonPGZ (wraps JSON)::

    [4 bytes]  magic   "PGZ\\x01"
    [32 bytes] SHA-256 of uncompressed payload
    [4 bytes]  uncompressed size (uint32 LE)
    [rest]     zlib-compressed payload

OrdinalPGZ — own envelope, two independent zlib streams::

    [4 bytes]  magic   "TXS\\x01"
    [32 bytes] SHA-256 of (header_compressed + text_compressed)
    [4 bytes]  header compressed size (uint32 LE)
    [4 bytes]  text block compressed size (uint32 LE)
    [H bytes]  header_compressed   ← zlib stream 1 (small)
    [T bytes]  text_compressed     ← zlib stream 2 (bulk)

    Header (uncompressed):
        [4 bytes]  entry count (uint32 LE)
        Per entry (sorted by filename):
            [2 bytes]  filename length (uint16 LE)
            [N bytes]  filename (UTF-8)
            [4 bytes]  text offset (uint32 LE, relative to text block start)
            [4 bytes]  text length (uint32 LE)

    Text block (uncompressed):
        Per file (same order):
            b"---- filename ----\\n"   (convenience label)
            raw UTF-8 text
            b"\\n"                     (separator)

    Offsets point past the label directly to the text content.
    Labels are cosmetic — visible when decompressing for inspection.
    Header-only read decompresses stream 1 only (~1% of the data).

LayeredTexts — delta-cache rotation over OrdinalPGZ layers::

    {key}.texts.0.pgz   — base layer (full snapshot)
    {key}.texts.1.pgz   — delta 1 (changed/new + tombstones)
    {key}.texts.2.pgz   — delta 2
    ...

Each layer is an immutable OrdinalPGZ file.
Tombstone = entry with text_length 0 (means "deleted, stop looking").
Read: scan layers newest-first, first hit per key wins.
Trim: merge oldest layers to keep count ≤ max_layers, rename remaining.
Compact = trim(1).
"""

from __future__ import annotations

import hashlib
import json
import logging
import struct
import time
import zlib
from pathlib import Path

log = logging.getLogger("parseltongue.pgz")

# ── PGZ envelope ──

_PGZ_MAGIC = b"PGZ\x01"
_PGZ_HEADER = struct.Struct("<4s32sI")  # magic + sha256 + size
_PGZ_MAX_PAYLOAD = 2**32  # uint32 size field in the envelope — format limit
_STREAM_BUF = 1 << 20  # flush compressed output to disk every ~1 MB


def pgz_write(path: Path, data: bytes):
    """Write data to a .pgz file with integrity header."""
    if len(data) >= _PGZ_MAX_PAYLOAD:
        raise ValueError(f"Payload exceeds PGZ 4 GiB format limit (uint32 size field): {path.name}")
    digest = hashlib.sha256(data).digest()
    compressed = zlib.compress(data, level=6)
    header = _PGZ_HEADER.pack(_PGZ_MAGIC, digest, len(data))
    _atomic_write_bytes(path, header + compressed)


def _atomic_write_bytes(path: Path, data: bytes):
    """Write via a sibling .tmp then rename — a kill mid-write never leaves
    a torn file at the real path."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def pgz_read(path: Path) -> bytes:
    """Read and verify a .pgz file. Raises on corruption."""
    raw = path.read_bytes()
    if len(raw) < _PGZ_HEADER.size:
        raise ValueError("File too small for .pgz header")
    magic, expected_digest, size = _PGZ_HEADER.unpack_from(raw)
    if magic != _PGZ_MAGIC:
        raise ValueError(f"Bad magic: {magic!r}")
    compressed = raw[_PGZ_HEADER.size :]
    data = zlib.decompress(compressed)
    if len(data) != size:
        raise ValueError(f"Size mismatch: expected {size}, got {len(data)}")
    actual_digest = hashlib.sha256(data).digest()
    if actual_digest != expected_digest:
        raise ValueError("SHA-256 integrity check failed")
    return data


# ── JsonPGZ ──


def json_pgz_write(path: Path, data: dict):
    """Stream a dict as JSON into a PGZ envelope.

    Chunked iterencode → sha256/zlib fed incrementally → file. Peak memory
    is bounded by the buffer size, not the payload size, and the GIL is
    released between chunks — a large save no longer blocks signal
    delivery (SIGTERM stays answerable mid-save). The fixed-size header
    is back-patched once digest and size are known; the write lands via
    .tmp + rename, so neither a kill mid-save nor a failed save ever
    clobbers the previous valid cache file.
    """
    encoder = json.JSONEncoder(separators=(",", ":"))
    digest = hashlib.sha256()
    compress = zlib.compressobj(level=6)
    size = 0
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(b"\x00" * _PGZ_HEADER.size)  # placeholder, patched below
            buf = bytearray()
            for chunk in encoder.iterencode(data):
                raw = chunk.encode("utf-8")
                size += len(raw)
                if size >= _PGZ_MAX_PAYLOAD:
                    # Abort as soon as the running total crosses the line —
                    # don't compress gigabytes the envelope can't describe.
                    raise ValueError(f"Payload exceeds PGZ 4 GiB format limit (uint32 size field): {path.name}")
                digest.update(raw)
                buf += compress.compress(raw)
                if len(buf) >= _STREAM_BUF:
                    f.write(buf)
                    buf.clear()
            buf += compress.flush()
            f.write(buf)
            f.seek(0)
            f.write(_PGZ_HEADER.pack(_PGZ_MAGIC, digest.digest(), size))
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def json_pgz_read(path: Path) -> dict:
    """Read a PGZ file and parse the payload as JSON."""
    return json.loads(pgz_read(path))


# ── OrdinalPGZ — two independent zlib streams ──

_TXS_MAGIC = b"TXS\x01"
_TXS_ENVELOPE = struct.Struct("<4s32sII")  # magic + sha256 + header_csize + text_csize
_ENTRY_HEAD = struct.Struct("<H")  # filename length
_ENTRY_TAIL = struct.Struct("<II")  # text offset, text length


def _build_ordinal_header(sorted_items: list[tuple[str, str]], offsets: list[tuple[int, int]]) -> bytes:
    """Build the binary header for OrdinalPGZ entries."""
    header = bytearray()
    header.extend(struct.pack("<I", len(sorted_items)))
    for (name, _text), (off, length) in zip(sorted_items, offsets):
        name_bytes = name.encode("utf-8")
        header.extend(_ENTRY_HEAD.pack(len(name_bytes)))
        header.extend(name_bytes)
        header.extend(_ENTRY_TAIL.pack(off, length))
    return bytes(header)


def _parse_ordinal_header(header: bytes) -> list[tuple[str, int, int]]:
    """Parse header → [(filename, text_offset, text_length), ...]."""
    if len(header) < 4:
        raise ValueError("OrdinalPGZ header too small")
    count = struct.unpack_from("<I", header, 0)[0]
    pos = 4
    entries: list[tuple[str, int, int]] = []
    for _ in range(count):
        name_len = _ENTRY_HEAD.unpack_from(header, pos)[0]
        pos += _ENTRY_HEAD.size
        name = header[pos : pos + name_len].decode("utf-8")
        pos += name_len
        off, length = _ENTRY_TAIL.unpack_from(header, pos)
        pos += _ENTRY_TAIL.size
        entries.append((name, off, length))
    return entries


def ordinal_pgz_write(path: Path, entries: dict[str, str]):
    """Write {filename: text} as OrdinalPGZ with two independent zlib streams.

    Entries are sorted by key. Header and text block are compressed
    separately so the header can be read without decompressing the bulk.
    The text stream is compressed per-entry — the uncompressed block is
    never materialized, so peak memory is the compressed size, not the
    corpus size. On-disk format is unchanged.
    """
    sorted_items = sorted(entries.items())
    compress = zlib.compressobj(level=6)
    text_parts: list[bytes] = []
    offsets: list[tuple[int, int]] = []
    pos = 0
    for name, text in sorted_items:
        label = f"---- {name} ----\n".encode()
        text_parts.append(compress.compress(label))
        pos += len(label)
        text_bytes = text.encode("utf-8")
        offsets.append((pos, len(text_bytes)))
        text_parts.append(compress.compress(text_bytes))
        pos += len(text_bytes)
        text_parts.append(compress.compress(b"\n"))
        pos += 1
    text_parts.append(compress.flush())
    text_compressed = b"".join(text_parts)
    header = _build_ordinal_header(sorted_items, offsets)
    header_compressed = zlib.compress(header, level=6)

    # Integrity covers both compressed streams
    digest = hashlib.sha256(header_compressed + text_compressed).digest()
    envelope = _TXS_ENVELOPE.pack(
        _TXS_MAGIC,
        digest,
        len(header_compressed),
        len(text_compressed),
    )
    _atomic_write_bytes(path, envelope + header_compressed + text_compressed)


def _ordinal_pgz_read_raw(path: Path) -> tuple[bytes, bytes]:
    """Read and verify an OrdinalPGZ file → (header_bytes, text_block_bytes).

    Decompresses both streams and verifies integrity.
    """
    raw = path.read_bytes()
    if len(raw) < _TXS_ENVELOPE.size:
        raise ValueError("File too small for OrdinalPGZ envelope")
    magic, expected_digest, hc_size, tc_size = _TXS_ENVELOPE.unpack_from(raw)
    if magic != _TXS_MAGIC:
        raise ValueError(f"Bad OrdinalPGZ magic: {magic!r}")

    payload = raw[_TXS_ENVELOPE.size :]
    header_compressed = payload[:hc_size]
    text_compressed = payload[hc_size : hc_size + tc_size]

    actual_digest = hashlib.sha256(header_compressed + text_compressed).digest()
    if actual_digest != expected_digest:
        raise ValueError("OrdinalPGZ SHA-256 integrity check failed")

    return zlib.decompress(header_compressed), zlib.decompress(text_compressed)


def _ordinal_pgz_read_header_only(path: Path) -> bytes:
    """Read and verify an OrdinalPGZ file → header bytes only.

    Decompresses only stream 1 (the header). The text block is NOT
    decompressed — this is the fast path for key enumeration.
    """
    raw = path.read_bytes()
    if len(raw) < _TXS_ENVELOPE.size:
        raise ValueError("File too small for OrdinalPGZ envelope")
    magic, expected_digest, hc_size, tc_size = _TXS_ENVELOPE.unpack_from(raw)
    if magic != _TXS_MAGIC:
        raise ValueError(f"Bad OrdinalPGZ magic: {magic!r}")

    payload = raw[_TXS_ENVELOPE.size :]
    header_compressed = payload[:hc_size]
    text_compressed = payload[hc_size : hc_size + tc_size]

    # Still verify integrity over both streams
    actual_digest = hashlib.sha256(header_compressed + text_compressed).digest()
    if actual_digest != expected_digest:
        raise ValueError("OrdinalPGZ SHA-256 integrity check failed")

    return zlib.decompress(header_compressed)


def ordinal_pgz_read(path: Path) -> dict[str, str]:
    """Read an OrdinalPGZ file → {filename: text}.

    Decompresses both streams. For header-only access use
    ordinal_pgz_header_keys() which skips the text block.
    """
    t0 = time.perf_counter()
    raw_size = path.stat().st_size
    header, text_block = _ordinal_pgz_read_raw(path)
    t_read = time.perf_counter() - t0
    entries = _parse_ordinal_header(header)
    t_parse = time.perf_counter() - t0 - t_read
    result = {name: text_block[off : off + length].decode("utf-8") for name, off, length in entries}
    t_total = time.perf_counter() - t0
    log.debug(
        "ordinal_pgz_read %s: file=%dB header=%dB text=%dB entries=%d "
        "read_decompress=%.3fs parse=%.3fs slice_decode=%.3fs total=%.3fs",
        path.name,
        raw_size,
        len(header),
        len(text_block),
        len(entries),
        t_read,
        t_parse,
        t_total - t_read - t_parse,
        t_total,
    )
    return result


def ordinal_pgz_decode(data: bytes) -> dict[str, str]:
    """Decode OrdinalPGZ from raw file bytes (not decompressed payload).

    Provided for compatibility — prefer ordinal_pgz_read(path) when
    you have a file path.
    """
    if len(data) < _TXS_ENVELOPE.size:
        raise ValueError("OrdinalPGZ data too small")
    magic, expected_digest, hc_size, tc_size = _TXS_ENVELOPE.unpack_from(data)
    if magic != _TXS_MAGIC:
        raise ValueError(f"Bad OrdinalPGZ magic: {magic!r}")

    payload = data[_TXS_ENVELOPE.size :]
    header_compressed = payload[:hc_size]
    text_compressed = payload[hc_size : hc_size + tc_size]

    actual_digest = hashlib.sha256(header_compressed + text_compressed).digest()
    if actual_digest != expected_digest:
        raise ValueError("OrdinalPGZ SHA-256 integrity check failed")

    header = zlib.decompress(header_compressed)
    text_block = zlib.decompress(text_compressed)
    entries = _parse_ordinal_header(header)
    return {name: text_block[off : off + length].decode("utf-8") for name, off, length in entries}


_TOMBSTONE = ""  # text_length == 0 in OrdinalPGZ means deleted


def ordinal_pgz_header_keys(path: Path) -> set[str]:
    """Read only the header of an OrdinalPGZ file → set of filenames.

    Decompresses only stream 1 (header). The text block zlib stream
    is never touched — fast path for key enumeration.
    """
    header = _ordinal_pgz_read_header_only(path)
    entries = _parse_ordinal_header(header)
    return {name for name, _off, _length in entries}


# ── LayeredTexts — delta-cache rotation ──


class LayeredTexts:
    """Delta-cache rotation over OrdinalPGZ layers.

    Each layer is an immutable OrdinalPGZ file. Newest layer has the
    highest number. Tombstones (empty string values) mark deletions.

    Layer files: {prefix}.texts.{n}.pgz

    Operations:
        write_delta  — append a new delta layer
        read         — merge all layers (newest-first, first hit wins)
        trim         — merge oldest layers to keep count ≤ max_layers
        compact      — trim(1), flatten everything into base
        layer_count  — number of layers on disk
        remove_all   — delete all layer files
    """

    def __init__(self, directory: Path, prefix: str, max_layers: int = 5):
        self._dir = directory
        self._prefix = prefix
        self._max_layers = max_layers

    def _layer_path(self, n: int) -> Path:
        return self._dir / f"{self._prefix}.texts.{n}.pgz"

    def layer_count(self) -> int:
        """Count existing layer files on disk."""
        n = 0
        while self._layer_path(n).exists():
            n += 1
        return n

    def layer_paths(self) -> list[Path]:
        """Return all existing layer paths in order [0, 1, ..., N-1]."""
        paths = []
        n = 0
        while True:
            p = self._layer_path(n)
            if not p.exists():
                break
            paths.append(p)
            n += 1
        return paths

    def write_base(self, entries: dict[str, str]):
        """Write a full base layer (layer 0). Removes any existing layers."""
        self.remove_all()
        self._dir.mkdir(parents=True, exist_ok=True)
        ordinal_pgz_write(self._layer_path(0), entries)

    def write_delta(self, changed: dict[str, str], deleted: set[str] | None = None):
        """Append a new delta layer with changed/new files and tombstones.

        changed: {filename: new_text} for added or modified files.
        deleted: set of filenames to tombstone.

        Auto-trims if layer count exceeds max_layers after write.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        n = self.layer_count()
        entries = dict(changed)
        for name in deleted or ():
            entries[name] = _TOMBSTONE
        ordinal_pgz_write(self._layer_path(n), entries)
        # Auto-trim if over limit
        if n + 1 > self._max_layers:
            self.trim(self._max_layers)

    def read(self) -> dict[str, str]:
        """Merge all layers → {filename: text}. Newest wins, tombstones remove.

        Scans layers from newest to oldest. First hit per key wins.
        Tombstones (empty string) mean the file was deleted — excluded
        from the result.
        """
        paths = self.layer_paths()
        if not paths:
            return {}
        log.info("LayerStack.read: merging %d layers (prefix=%s)", len(paths), self._prefix)
        t_start = time.perf_counter()
        result: dict[str, str] = {}
        seen: set[str] = set()
        layer_bytes = 0
        layer_entries = 0
        # Newest first
        for path in reversed(paths):
            t_layer = time.perf_counter()
            layer = ordinal_pgz_read(path)
            layer_bytes += path.stat().st_size
            layer_entries += len(layer)
            kept = 0
            for name, text in layer.items():
                if name not in seen:
                    seen.add(name)
                    if text:  # skip tombstones
                        result[name] = text
                        kept += 1
            log.debug(
                "LayerStack.read: %s %.3fs entries=%d kept=%d",
                path.name,
                time.perf_counter() - t_layer,
                len(layer),
                kept,
            )
        log.info(
            "LayerStack.read: done %d layers, %d bytes on disk, %d total entries → %d merged, %.2fs",
            len(paths),
            layer_bytes,
            layer_entries,
            len(result),
            time.perf_counter() - t_start,
        )
        return result

    def trim(self, max_layers: int):
        """Merge oldest layers until count ≤ max_layers, rename remaining.

        Example: 13 layers, trim(10):
          merge layers 0+1+2+3 → new base 0
          rename old 4→1, 5→2, ..., 12→9
          result: 10 layers
        """
        paths = self.layer_paths()
        count = len(paths)
        if count <= max_layers:
            return

        # How many old layers to merge: excess + 1 (they become 1 base)
        merge_count = count - max_layers + 1

        # Merge oldest layers: base-up, oldest-first, newest wins
        merged: dict[str, str] = {}
        for path in paths[:merge_count]:
            layer = ordinal_pgz_read(path)
            for name, text in layer.items():
                if text:
                    merged[name] = text
                else:
                    # Tombstone: remove from merged if present
                    merged.pop(name, None)

        # Write merged as new base to a temp, then swap
        new_base = self._layer_path(0).with_suffix(".pgz.tmp")
        ordinal_pgz_write(new_base, merged)

        # Delete old merged layers
        for path in paths[:merge_count]:
            path.unlink()

        # Rename remaining layers to close gaps: old merge_count→1, merge_count+1→2, ...
        for i, path in enumerate(paths[merge_count:]):
            new_path = self._layer_path(i + 1)
            if path != new_path:
                path.rename(new_path)

        # Move new base into position
        new_base.rename(self._layer_path(0))

    def compact(self):
        """Flatten all layers into a single base. Alias for trim(1)."""
        self.trim(1)

    def remove_all(self):
        """Delete all layer files."""
        for path in self.layer_paths():
            path.unlink(missing_ok=True)
