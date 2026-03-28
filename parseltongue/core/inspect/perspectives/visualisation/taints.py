"""Taint computation — single source of truth for all viz consumers.

A taint source is any node whose evidence doesn't pass the predicate
(default: no evidence, or evidence with unverified status).  Taint
propagates forward through edges: any node that consumes a tainted
node is itself tainted.

Usage::

    from .taints import compute_taints, default_predicate

    result = compute_taints(items, edges)
    # result.sources  — set of names that are taint origins
    # result.tainted  — set of all tainted names (sources + propagated)
    # result.reasons  — {name: reason_str} for every tainted node

Custom predicates::

    def my_pred(item):
        # item is the full item dict (id, kind, value, evidence, ...)
        ev = item.get("evidence", [])
        if not ev:
            return True, "no evidence"
        if any(e.get("status") == "unverified" for e in ev):
            return True, "unverified evidence"
        return False, None

    result = compute_taints(items, edges, predicate=my_pred)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class TaintResult:
    """Result of taint computation."""

    sources: set[str] = field(default_factory=set)
    tainted: set[str] = field(default_factory=set)
    reasons: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict:
        """Serialize for embedding in HTML/JS."""
        return {
            "sources": sorted(self.sources),
            "tainted": sorted(self.tainted),
            "reasons": self.reasons,
        }


# Type alias for predicate: (item_dict) -> (is_source, reason | None)
TaintPredicate = Callable[[dict], tuple[bool, str | None]]


def default_predicate(item: dict) -> tuple[bool, str | None]:
    """Default taint predicate.

    A node is a taint source if:
    - It has no evidence at all, OR
    - Any evidence entry has status != verified/derived/manual, OR
    - Status is 'manual' but the signature doesn't match any session
      participant in the logbook (when logbook is available)
    """
    ev = item.get("evidence", [])
    if not ev:
        return True, "no evidence"
    ok_statuses = {"verified", "derived", "manual"}
    logbook = item.get("_logbook")
    # Collect known participants from logbook
    known_participants: set[str] | None = None
    known_assistants: set[str] | None = None
    if logbook:
        known_participants = set()
        known_assistants = set()
        for entry in logbook:
            u = entry.get("user", "")
            a = entry.get("assistant", "")
            if u:
                known_participants.add(u)
            if a:
                known_assistants.add(a)
    for e in ev:
        status = e.get("status", "")
        if status not in ok_statuses:
            return True, f"unverified ({status or 'unknown'})"
        if status == "manual":
            sig = e.get("signature") or ""
            if known_participants is None:
                # No logbook — can't verify who signed, taint it
                return True, "manually verified (no session log)"
            if not sig:
                return True, "manually verified (no signature)"
            if sig in known_participants:
                continue  # user-signed — clean
            if known_assistants and sig in known_assistants:
                return True, f"signed by '{sig}', role: assistant — waiting for user's signature"
            return True, f"signed by '{sig}' — not a known session participant"
    return False, None


def compute_taints(
    items: list[dict],
    edges: list[dict],
    predicate: TaintPredicate | None = None,
    structure_items: list[dict] | None = None,
    logbook: list[dict] | None = None,
) -> TaintResult:
    """Compute taint sources and propagation.

    Args:
        items: DATA items (primary nodes in the view).
        edges: LAYERS edges [{source, target, type}].
        predicate: Custom predicate. Default: ``default_predicate``.
        structure_items: STRUCTURE_DATA items — used for evidence lookup
            when items themselves lack evidence (e.g. notebook view).
            Falls back to items if not provided.
        logbook: Session log entries from the bench logbook. Passed to
            the predicate via ``item["_logbook"]`` so custom predicates
            can use session history for taint decisions.

    Returns:
        TaintResult with sources, full tainted set, and per-node reasons.
    """
    if predicate is None:
        predicate = default_predicate

    # Build evidence index from structure_items (richer) falling back to items
    ev_by_id: dict[str, list] = {}
    for it in structure_items or []:
        ev = it.get("evidence", [])
        if ev:
            ev_by_id[it["id"]] = ev
    for it in items:
        if it["id"] not in ev_by_id:
            ev = it.get("evidence", [])
            if ev:
                ev_by_id[it["id"]] = ev

    # All known IDs from structure (only structured nodes can propagate)
    struct_ids = set(ev_by_id) if structure_items else {it["id"] for it in items}

    # Find taint sources
    sources: set[str] = set()
    reasons: dict[str, str] = {}

    for it in items:
        name = it["id"]
        # std nodes are trusted — never taint sources
        if name.startswith("std."):
            continue
        if name not in struct_ids and structure_items:
            continue
        # Build a lookup item with merged evidence for the predicate
        lookup = dict(it)
        if name in ev_by_id:
            lookup["evidence"] = ev_by_id[name]
        if logbook is not None:
            lookup["_logbook"] = logbook
        is_source, reason = predicate(lookup)
        if is_source:
            sources.add(name)
            if reason:
                reasons[name] = reason

    # Build forward adjacency (source → children that consume it)
    children: dict[str, list[str]] = {}
    for edge in edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src and tgt:
            children.setdefault(src, []).append(tgt)

    # BFS propagation — std nodes are immune (trusted library)
    tainted = set(sources)
    queue = list(sources)
    while queue:
        node = queue.pop()
        for child in children.get(node, []):
            if child not in tainted and not child.startswith("std."):
                tainted.add(child)
                queue.append(child)
                # Record propagation reason
                if child not in reasons:
                    reasons[child] = f"depends on tainted: {node}"

    return TaintResult(sources=sources, tainted=tainted, reasons=reasons)
