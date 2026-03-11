"""Merkle tree structural integrity for pltg blocks.

Complements :mod:`integrity.chain`, which provides **linear
integrity** (hash chain across blocks).  This module provides
**structural integrity** within a single block.

Linear vs Structural
--------------------

*Linear integrity* answers: "has the sequence of blocks changed?"
It treats each block as an opaque blob and chains their hashes.

*Structural integrity* answers: "which expressions inside a block
changed?"  It parses the block into individual S-expressions and
builds a Merkle tree over them.

Merkle Tree Construction
------------------------

A pltg block contains N top-level S-expressions (directives).
Each is hashed as a leaf.  Leaves are paired bottom-up into a
balanced binary tree::

    Block:
        (fact revenue 15 :origin "Q3")         → H₀
        (defterm margin (- revenue cost))      → H₁
        (derive check margin :using (axiom))   → H₂

    Tree:
                  root = SHA-256(H₀₁ ‖ H₂)
                 /                          \\
        H₀₁ = SHA-256(H₀ ‖ H₁)            H₂
        /                    \\               |
       H₀                   H₁             H₂

Properties:

- Editing one expression changes only its leaf and the path to root.
  All other nodes keep their hashes — O(log N) recomputation.
- Two blocks with identical expressions in the same order produce
  identical roots.
- Proof of membership for any single expression is O(log N) hashes.
- SHA-256 throughout, consistent with :mod:`integrity.chain`.

S-Expression Normalisation
--------------------------

Before hashing, each parsed expression is serialised back to canonical
S-expression form via :func:`atoms.to_sexp`.  This normalises whitespace,
quoting, and formatting so that semantically identical expressions always
produce the same hash regardless of surface syntax differences.

Merkle Proofs
-------------

A proof path lets you verify that a specific expression is part of a
block without the full tree.  The path contains O(log N) sibling hashes.
Verification walks from leaf to root, combining with siblings::

    proof = proof_path(tree, leaf_index=1)
    assert verify_proof(leaf_hash, proof, tree.hash)

Tree Diffing
------------

:func:`diff_trees` compares two Merkle trees (e.g. before/after edit)
and returns which expressions were added, removed, or modified.  Only
leaves with differing hashes are reported.

All functions are pure — no I/O, no state.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ..atoms import parse_all, to_sexp

# ── SHA-256 (Bitcoin-compatible) ──


def _sha256(data: str) -> str:
    """SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# ── Merkle node ──


@dataclass
class MerkleNode:
    """A node in the Merkle tree.

    Leaves have ``content`` (the normalised S-expression text) and no
    children.  Interior nodes have two children and no content.  The
    ``hash`` field is always populated.
    """

    hash: str
    content: str = ""
    children: list[MerkleNode] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        """True if this is a leaf (single expression)."""
        return not self.children

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        if self.is_leaf:
            return {"h": self.hash, "c": self.content}
        return {"h": self.hash, "ch": [c.to_dict() for c in self.children]}

    @classmethod
    def from_dict(cls, d: dict) -> "MerkleNode":
        """Deserialize from dict."""
        if "ch" in d:
            return cls(hash=d["h"], children=[cls.from_dict(c) for c in d["ch"]])
        return cls(hash=d["h"], content=d.get("c", ""))

    @property
    def leaf_count(self) -> int:
        """Number of leaves in this subtree."""
        if self.is_leaf:
            return 1
        return sum(c.leaf_count for c in self.children)


# ── Tree construction ──


def merkle_leaf(expr) -> MerkleNode:
    """Create a leaf node from a parsed S-expression.

    The expression is normalised via ``to_sexp`` before hashing,
    so whitespace and formatting differences don't affect the hash.

    Parameters
    ----------
    expr : list | Symbol | str | int | float | bool
        A parsed S-expression (output of :func:`atoms.parse`).

    Returns

    -------
    MerkleNode
        Leaf node with hash and normalised content.
    """
    text = to_sexp(expr)
    return MerkleNode(hash=_sha256(text), content=text)


def merkle_combine(nodes: list[MerkleNode]) -> MerkleNode:
    """Combine leaf/interior nodes into a balanced binary Merkle tree.

    Pairs nodes left-to-right, combining each pair into a parent
    whose hash is SHA-256(left.hash ‖ right.hash).  Odd nodes are
    promoted to the next level unpaired.  Recurses until one root
    remains.

    Parameters
    ----------
    nodes : list[MerkleNode]
        One or more nodes to combine.

    Returns
    -------
    MerkleNode
        The root of the combined tree.
    """
    if not nodes:
        return MerkleNode(hash=_sha256(""))
    if len(nodes) == 1:
        return nodes[0]

    parents: list[MerkleNode] = []
    for i in range(0, len(nodes), 2):
        if i + 1 < len(nodes):
            left, right = nodes[i], nodes[i + 1]
            combined = _sha256(left.hash + right.hash)
            parents.append(MerkleNode(hash=combined, children=[left, right]))
        else:
            parents.append(nodes[i])

    return merkle_combine(parents)


def build_merkle(block_content: str) -> MerkleNode:
    """Build a Merkle tree from a pltg block's source text.

    Parses all top-level S-expressions, creates a leaf for each,
    then combines into a balanced binary tree.

    Parameters
    ----------
    block_content : str
        Raw pltg source text (may include ``;; pltg`` marker line).

    Returns
    -------
    MerkleNode
        Root of the Merkle tree.
    """
    # Strip pltg marker if present
    lines = block_content.splitlines()
    cleaned = "\n".join(ln for ln in lines if not ln.strip().startswith(";; pltg"))
    exprs = parse_all(cleaned)
    if not exprs:
        return MerkleNode(hash=_sha256(""))
    leaves = [merkle_leaf(e) for e in exprs]
    return merkle_combine(leaves)


def merkle_root(block_content: str) -> str:
    """Compute the Merkle root hash for a pltg block.

    Shorthand for ``build_merkle(block_content).hash``.
    """
    return build_merkle(block_content).hash


# ── Proof path ──


@dataclass
class ProofStep:
    """One step in a Merkle inclusion proof.

    ``sibling_hash`` is the hash of the sibling node.
    ``side`` indicates whether the sibling is on the ``"left"``
    or ``"right"`` — i.e., the position of the *sibling*, not
    the target.
    """

    sibling_hash: str
    side: str  # "left" | "right"


def proof_path(root: MerkleNode, leaf_index: int) -> list[ProofStep] | None:
    """Extract the inclusion proof for a leaf by its index.

    The proof is a list of sibling hashes from leaf to root.
    Combined with the leaf's own hash, it can reconstruct the
    root hash — proving the leaf is part of the tree without
    revealing other leaves.

    Parameters
    ----------
    root : MerkleNode
        Root of the Merkle tree.
    leaf_index : int
        Zero-based index of the target leaf (left-to-right order).

    Returns
    -------
    list[ProofStep] | None
        Proof steps from leaf to root, or None if index is invalid.
    """
    leaves = collect_leaves(root)
    if leaf_index < 0 or leaf_index >= len(leaves):
        return None

    target_hash = leaves[leaf_index].hash
    path: list[ProofStep] = []
    if _find_path(root, target_hash, path):
        return path
    return None


def verify_proof(leaf_hash: str, path: list[ProofStep], expected_root: str) -> bool:
    """Verify a Merkle inclusion proof.

    Walks from leaf to root, combining with each sibling hash.
    Returns True if the reconstructed root matches ``expected_root``.

    Parameters
    ----------
    leaf_hash : str
        SHA-256 hash of the leaf expression.
    path : list[ProofStep]
        Proof steps as returned by :func:`proof_path`.
    expected_root : str
        Expected root hash to verify against.
    """
    current = leaf_hash
    for step in path:
        if step.side == "left":
            current = _sha256(step.sibling_hash + current)
        else:
            current = _sha256(current + step.sibling_hash)
    return current == expected_root


# ── Tree diffing ──


def diff_trees(old: MerkleNode, new: MerkleNode) -> list[tuple[str, str, str]]:
    """Compare two Merkle trees leaf-by-leaf.

    Returns a list of changes.  Each entry is ``(status, old_content,
    new_content)`` where status is:

    - ``"modified"`` — expression at this position changed
    - ``"added"`` — new tree has an extra expression
    - ``"removed"`` — old tree had an expression that's gone

    Only leaves with differing hashes are reported.  Unchanged
    expressions are omitted.

    Parameters
    ----------
    old, new : MerkleNode
        Roots of the two trees to compare.
    """
    old_leaves = collect_leaves(old)
    new_leaves = collect_leaves(new)
    changes: list[tuple[str, str, str]] = []
    max_len = max(len(old_leaves), len(new_leaves))

    for i in range(max_len):
        if i >= len(old_leaves):
            changes.append(("added", "", new_leaves[i].content))
        elif i >= len(new_leaves):
            changes.append(("removed", old_leaves[i].content, ""))
        elif old_leaves[i].hash != new_leaves[i].hash:
            changes.append(("modified", old_leaves[i].content, new_leaves[i].content))

    return changes


# ── Helpers ──


def collect_leaves(node: MerkleNode) -> list[MerkleNode]:
    """Collect all leaf nodes in left-to-right order."""
    if node.is_leaf:
        return [node]
    result: list[MerkleNode] = []
    for child in node.children:
        result.extend(collect_leaves(child))
    return result


def _find_path(node: MerkleNode, target_hash: str, path: list[ProofStep]) -> bool:
    """Recursively locate a leaf by hash and build the proof path."""
    if node.is_leaf:
        return node.hash == target_hash

    if len(node.children) == 2:
        left, right = node.children
        if _find_path(left, target_hash, path):
            path.append(ProofStep(sibling_hash=right.hash, side="right"))
            return True
        if _find_path(right, target_hash, path):
            path.append(ProofStep(sibling_hash=left.hash, side="left"))
            return True
    elif len(node.children) == 1:
        return _find_path(node.children[0], target_hash, path)

    return False
