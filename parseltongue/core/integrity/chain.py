"""Sequential hash chain — linear integrity over ordered blocks.

Same primitive as Bitcoin's block chain::

    H₀ = SHA-256(block_0_content)
    H₁ = SHA-256(block_1_content ‖ H₀)
    H₂ = SHA-256(block_2_content ‖ H₁)
    ...

Properties:

- Changing block N invalidates N, N+1, N+2, ...
- Inserting or removing a block invalidates everything after it
- Verification is sequential from genesis (block 0)
- SHA-256 throughout

Block States
------------

``VALID``
    Chain hash matches.

``INVALID``
    Hash verification failed — the **break point**.

``STALE``
    After an ``INVALID``.  Chain is broken above, so this block's
    hash cannot be verified even if its own content is unchanged.

All functions are pure — no I/O, no mutation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum, auto

# ── SHA-256 chain hash ──


def chain_hash(content: str, prev: str = "") -> str:
    """SHA-256(content ‖ prev_hash).  Genesis block uses empty prev."""
    return hashlib.sha256((content + prev).encode("utf-8")).hexdigest()


def build_chain(blocks: list[str]) -> list[str]:
    """Compute expected hash chain from a list of block contents."""
    hashes: list[str] = []
    prev = ""
    for content in blocks:
        h = chain_hash(content, prev)
        hashes.append(h)
        prev = h
    return hashes


# ── Integrity types ──


class BlockStatus(Enum):
    """Integrity state of a single block."""

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
    """Complete integrity check result."""

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


def check_chain(source_blocks: list[str], stored: dict[int, tuple[str, str]]) -> IntegrityResult:
    """Verify stored hashes against source blocks.

    Parameters
    ----------
    source_blocks : list[str]
        Ordered block contents from the source.
    stored : dict[int, tuple[str, str]]
        block_num → (stored_hash, stored_content) from the companion/cache.

    Returns
    -------
    IntegrityResult
    """
    expected = build_chain(source_blocks)
    result = IntegrityResult(chain=expected)

    if not source_blocks:
        return result

    chain_broken = False
    for block_num in range(len(source_blocks)):
        stored_hash, comp_content = stored.get(block_num, ("", ""))

        if chain_broken:
            result.blocks[block_num] = BlockIntegrity(
                BlockStatus.STALE, source_blocks[block_num], comp_content, stored_hash=stored_hash
            )
            continue

        if block_num < len(expected) and stored_hash == expected[block_num]:
            result.valid.add(block_num)
            result.blocks[block_num] = BlockIntegrity(BlockStatus.VALID, stored_hash=stored_hash)
        else:
            result.blocks[block_num] = BlockIntegrity(
                BlockStatus.INVALID, source_blocks[block_num], comp_content, stored_hash=stored_hash
            )
            chain_broken = True

    return result
