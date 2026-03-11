"""Integrity verification primitives.

Two complementary integrity mechanisms:

- **Linear** (``chain``): Sequential hash chain over ordered blocks.
  Changing block N invalidates N, N+1, N+2, ...  Same primitive as
  Bitcoin's block chain.

- **Structural** (``merkle``): Merkle tree over S-expressions within
  a single block.  Identifies *which* expressions changed with
  O(log N) recomputation.
"""

from .chain import BlockIntegrity, BlockStatus, IntegrityResult, chain_hash
from .merkle import (
    MerkleNode,
    ProofStep,
    build_merkle,
    collect_leaves,
    diff_trees,
    merkle_combine,
    merkle_leaf,
    merkle_root,
    proof_path,
    verify_proof,
)

__all__ = [
    # Chain (linear integrity)
    "chain_hash",
    "BlockStatus",
    "BlockIntegrity",
    "IntegrityResult",
    # Merkle (structural integrity)
    "MerkleNode",
    "build_merkle",
    "merkle_root",
    "merkle_leaf",
    "merkle_combine",
    "collect_leaves",
    "diff_trees",
    "proof_path",
    "verify_proof",
    "ProofStep",
]
