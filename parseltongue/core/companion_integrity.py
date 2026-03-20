"""Companion file integrity — pgmd ↔ companion wire format.

Applies :mod:`integrity.chain` (sequential hash chain) to the
companion file format.  Companion-specific concerns: block markers,
regex parsing, ordering, duplicate detection, text manipulation.

For the abstract chain primitives, see :mod:`integrity.chain`.
For structural (Merkle) integrity, see :mod:`integrity.merkle`.
"""

from __future__ import annotations

import re

from .integrity.chain import IntegrityResult, chain_hash, check_chain
from .integrity.chain import build_chain as _build_chain_generic
from .pgmd import parse_pgmd

# ── Companion block markers ──

BLOCK_START_FMT = ";; @@block {n} {h}"
BLOCK_END_FMT = ";; @@end {n}"
BLOCK_RE = re.compile(
    r";; @@block (\d+) ([0-9a-f]{64})\n(.*?)\n;; @@end \1",
    re.DOTALL,
)


def build_chain(pgmd_source: str) -> list[str]:
    """Compute expected hash chain from pltg blocks in pgmd source."""
    pltg = [b for b in parse_pgmd(pgmd_source) if b.kind == "pltg"]
    return _build_chain_generic([b.content for b in pltg])


# ── Companion structural checks ──


def check_duplicates(companion_text: str) -> list[int]:
    """Detect block numbers that appear more than once in companion text.

    A well-formed companion file has exactly one entry per block number.
    Duplicates indicate a write error (append without checking existence)
    or concurrent modification.  Each block number is reported once,
    in order of first occurrence.

    Parameters
    ----------
    companion_text : str
        Raw companion file content.

    Returns
    -------
    list[int]
        Block numbers with duplicates, in order of first occurrence.
        Empty list if no duplicates.
    """
    counts: dict[int, int] = {}
    order: list[int] = []
    if companion_text and companion_text.strip():
        for m in BLOCK_RE.finditer(companion_text):
            num = int(m.group(1))
            counts[num] = counts.get(num, 0) + 1
            if counts[num] == 2:
                order.append(num)
    return order


def resolve_duplicates(companion_text: str, block_num: int, canonical_hash: str) -> str:
    """Resolve duplicate entries for a single block number.

    Keeps the entry whose stored hash matches ``canonical_hash`` and
    removes all other occurrences of that block number.

    Parameters
    ----------
    companion_text : str
        Raw companion file content with duplicates.
    block_num : int
        The block number to de-duplicate.
    canonical_hash : str
        The correct SHA-256 hash for this block.

    Returns
    -------
    str
        Companion text with exactly one entry for ``block_num``.
    """
    found_canonical = False

    def _pick(m: re.Match) -> str:
        nonlocal found_canonical
        if int(m.group(1)) != block_num:
            return m.group(0)
        if not found_canonical and m.group(2) == canonical_hash:
            found_canonical = True
            return m.group(0)
        return ""

    text = BLOCK_RE.sub(_pick, companion_text)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip() + "\n" if text.strip() else ""


def check_ordering(companion_text: str) -> bool:
    """Detect misordered blocks in companion text.

    Parameters
    ----------
    companion_text : str
        Raw companion file content.

    Returns
    -------
    bool
        True if blocks are out of order.  False if correctly ordered
        or empty.
    """
    seen: list[int] = []
    if companion_text and companion_text.strip():
        for m in BLOCK_RE.finditer(companion_text):
            seen.append(int(m.group(1)))
    return seen != sorted(seen)


def repair_ordering(companion_text: str) -> str:
    """Reorder companion blocks by ascending block number.

    Parameters
    ----------
    companion_text : str
        Raw companion file content, possibly misordered.

    Returns
    -------
    str
        Companion text with blocks in ascending order.
    """
    blocks: dict[int, str] = {}
    for m in BLOCK_RE.finditer(companion_text):
        num = int(m.group(1))
        blocks[num] = m.group(0)
    if not blocks:
        return companion_text
    return "\n".join(blocks[n] for n in sorted(blocks)) + "\n"


# ── Pure integrity check ──


def check_integrity(pgmd_source: str, companion_text: str) -> IntegrityResult:
    """Verify companion against pgmd source using hash chains.

    Walks blocks sequentially.  Each block's companion hash is compared
    against the expected chain hash.  First failure is INVALID; all
    subsequent blocks are STALE (chain broken above).  Blocks not in
    the companion have an empty companion hash — still INVALID.

    Returns ``IntegrityResult`` with chain, valid set, and per-block detail.
    """
    pltg = [b for b in parse_pgmd(pgmd_source) if b.kind == "pltg"]

    if not pltg:
        return IntegrityResult()

    # Parse companion entries: block_num → (stored_hash, content)
    companion_data: dict[int, tuple[str, str]] = {}
    if companion_text and companion_text.strip():
        for m in BLOCK_RE.finditer(companion_text):
            companion_data[int(m.group(1))] = (m.group(2), m.group(3))

    result = check_chain([b.content for b in pltg], companion_data)

    # Add companion structural checks
    result.duplicates = check_duplicates(companion_text)
    result.misordered = check_ordering(companion_text)

    return result


# ── Companion text manipulation (pure, returns new strings) ──


def format_block(block_num: int, content: str, hash_hex: str) -> str:
    """Format a block with its markers."""
    start = BLOCK_START_FMT.format(n=block_num, h=hash_hex)
    end = BLOCK_END_FMT.format(n=block_num)
    return f"{start}\n{content}\n{end}"


def insert_block(companion_text: str, block_num: int, content: str, chain: list[str]) -> str:
    """Insert a block in order by block number.  Returns new text.

    Finds the correct position among existing blocks so that block
    numbers stay sequential.  If block_num already exists, replaces it.
    """
    h = chain[block_num] if block_num < len(chain) else chain_hash(content)
    segment = format_block(block_num, content, h)

    # Check if block already exists — replace it
    if re.search(rf";; @@block {block_num} ", companion_text):
        return replace_block(companion_text, block_num, content, chain)

    # Find insertion point: after the last block with number < block_num
    last_end = 0
    for m in BLOCK_RE.finditer(companion_text):
        if int(m.group(1)) < block_num:
            last_end = m.end()

    if last_end == 0 and not companion_text.strip():
        return segment + "\n"

    if last_end == 0:
        # Insert before everything
        return segment + "\n" + companion_text
    else:
        before = companion_text[:last_end]
        after = companion_text[last_end:]
        if not before.endswith("\n"):
            before += "\n"
        return before + segment + "\n" + after.lstrip("\n")


def replace_block(companion_text: str, block_num: int, content: str, chain: list[str]) -> str:
    """Replace an existing block in companion text.  Returns new text."""
    h = chain[block_num] if block_num < len(chain) else chain_hash(content)
    segment = format_block(block_num, content, h)
    return BLOCK_RE.sub(
        lambda m: segment if int(m.group(1)) == block_num else m.group(0),
        companion_text,
    )


def clear_block(companion_text: str, block_num: int) -> str:
    """Clear a block's content in companion text (keeps markers, empties content).

    The empty content will naturally hash-mismatch on integrity check.
    """
    empty = format_block(block_num, "", chain_hash(""))
    return BLOCK_RE.sub(
        lambda m: empty if int(m.group(1)) == block_num else m.group(0),
        companion_text,
    )
