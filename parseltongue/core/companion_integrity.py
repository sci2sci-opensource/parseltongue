"""Cryptographic integrity verification for pgmd ↔ companion pairs.

Hash Chain
----------

Executable pltg blocks in a pgmd file form a sequential hash chain
(same primitive as Bitcoin's block chain):

    H₀ = SHA-256(block_0_content)
    H₁ = SHA-256(block_1_content ‖ H₀)
    H₂ = SHA-256(block_2_content ‖ H₁)
    ...

Properties:

- Changing block N invalidates N, N+1, N+2, ...
- Inserting or removing a block invalidates everything after it
- Verification is sequential from genesis (block 0)
- SHA-256 for Bitcoin-compatible proof of integrity

Block States
------------

``VALID``
    Chain hash matches.  Companion content is identical to source.

``INVALID``
    Hash verification failed.  Source or companion changed after
    execution.  This is the **break point** — first block where
    the chain fails.

``STALE``
    After an ``INVALID``.  Chain is broken above, so this block's
    hash cannot be verified even if its own content is unchanged.

All functions are pure — no I/O, no mutation, no UI.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum, auto

from .pgmd import parse_pgmd

# ── Companion block markers ──

BLOCK_START_FMT = ";; @@block {n} {h}"
BLOCK_END_FMT = ";; @@end {n}"
BLOCK_RE = re.compile(
    r";; @@block (\d+) ([0-9a-f]{64})\n(.*?)\n;; @@end \1",
    re.DOTALL,
)


# ── SHA-256 chain hash ──


def chain_hash(content: str, prev: str = "") -> str:
    """SHA-256(content ‖ prev_hash).  Genesis block uses empty prev."""
    return hashlib.sha256((content + prev).encode("utf-8")).hexdigest()


def build_chain(pgmd_source: str) -> list[str]:
    """Compute expected hash chain from pltg blocks in pgmd source."""
    pltg = [b for b in parse_pgmd(pgmd_source) if b.kind == "pltg"]
    hashes: list[str] = []
    prev = ""
    for block in pltg:
        h = chain_hash(block.content, prev)
        hashes.append(h)
        prev = h
    return hashes


# ── Integrity types ──


class BlockStatus(Enum):
    """Integrity state of a single pltg block."""

    VALID = auto()
    INVALID = auto()
    STALE = auto()


@dataclass
class BlockIntegrity:
    """Integrity detail for one block."""

    status: BlockStatus
    source_content: str = ""
    companion_content: str = ""
    stored_hash: str = ""


@dataclass
class IntegrityResult:
    """Complete integrity check between pgmd source and companion."""

    chain: list[str] = field(default_factory=list)
    valid: set[int] = field(default_factory=set)
    blocks: dict[int, BlockIntegrity] = field(default_factory=dict)
    misordered: bool = False
    duplicates: list[int] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True when every block is VALID."""
        return all(b.status == BlockStatus.VALID for b in self.blocks.values())

    @property
    def break_point(self) -> int | None:
        """Block number of the first INVALID, or None."""
        for bn in sorted(self.blocks):
            if self.blocks[bn].status == BlockStatus.INVALID:
                return bn
        return None


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

    Multiple entries for the same block number means something went
    wrong (failed replace, concurrent write, etc.).  This function
    keeps the entry whose stored hash matches ``canonical_hash`` and
    removes all other occurrences of that block number — including
    same-hash copies that appear after the canonical one.

    Non-duplicate blocks are left untouched.

    Parameters
    ----------
    companion_text : str
        Raw companion file content with duplicates.
    block_num : int
        The block number to de-duplicate.
    canonical_hash : str
        The correct SHA-256 hash for this block.  The first entry
        matching this hash is kept; all others for ``block_num``
        are removed.

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

    The hash chain assumes blocks appear in sequential order
    (0, 1, 2, ...).  If block N appears after block N+K in the file,
    the chain cannot be verified correctly even if individual hashes
    are valid.

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

    Sorts all block entries so they appear in sequential order as
    the hash chain requires.  Does not modify block content or hashes.

    If duplicates exist, the last occurrence of each block number
    is kept.  Use :func:`resolve_duplicates` first to choose the
    correct entry before reordering.

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
    expected = build_chain(pgmd_source)
    pltg = [b for b in parse_pgmd(pgmd_source) if b.kind == "pltg"]
    result = IntegrityResult(chain=expected)

    if not pltg:
        return result

    # Structural checks
    result.duplicates = check_duplicates(companion_text)
    result.misordered = check_ordering(companion_text)

    # Parse companion entries: block_num → (stored_hash, content)
    companion_data: dict[int, tuple[str, str]] = {}
    if companion_text and companion_text.strip():
        for m in BLOCK_RE.finditer(companion_text):
            companion_data[int(m.group(1))] = (m.group(2), m.group(3))

    chain_broken = False
    for block_num in range(len(pltg)):
        stored_hash, comp_content = companion_data.get(block_num, ("", ""))

        if chain_broken:
            result.blocks[block_num] = BlockIntegrity(
                BlockStatus.STALE, pltg[block_num].content, comp_content, stored_hash=stored_hash
            )
            continue

        if block_num < len(expected) and stored_hash == expected[block_num]:
            result.valid.add(block_num)
            result.blocks[block_num] = BlockIntegrity(BlockStatus.VALID, stored_hash=stored_hash)
        else:
            result.blocks[block_num] = BlockIntegrity(
                BlockStatus.INVALID, pltg[block_num].content, comp_content, stored_hash=stored_hash
            )
            chain_broken = True

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
