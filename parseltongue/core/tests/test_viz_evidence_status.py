"""Test that _enrich_items_from_structure produces correct evidence status for all origin types.

Also tests taint classification: mirrors the JS taint logic from graph.js to ensure
the Python data produces correct taint/clean results in the graph view.
"""

from dataclasses import dataclass, field
from typing import Any

from parseltongue.core.atoms import Axiom, Evidence, Term, Theorem
from parseltongue.core.engine import Fact
from parseltongue.core.inspect.perspectives.visualisation.renderer import (
    _enrich_items_from_structure,
)
from parseltongue.core.inspect.probe_core_to_consequence import Node, NodeKind


@dataclass
class FakeStructure:
    graph: dict = field(default_factory=dict)
    depths: dict = field(default_factory=dict)


def _is_taint_source(item: dict) -> bool:
    """Mirror graph.js taint logic: no evidence or any non-ok status → taint source."""
    ev = item.get("evidence", [])
    if not ev:
        return True
    return not all(e.get("status") in ("verified", "derived", "manual") for e in ev)


def _make_item(name: str) -> dict:
    return {"id": name, "kind": "fact", "value": "", "depth": 0, "inputs": [], "evidence": []}


def _make_node(name: str, kind: NodeKind, atom: Any) -> Node:
    return Node(name=name, kind=kind, value=True, inputs=[], atom=atom)


class TestEvidenceStatusVerified:
    """Evidence with verified=True → status 'verified'."""

    def test_fact_with_verified_evidence(self):
        ev = Evidence(document="doc.py", quotes=["class Foo:"], verified=True)
        fact = Fact(name="f1", wff=True, origin=ev)
        structure = FakeStructure(graph={"f1": _make_node("f1", NodeKind.FACT, fact)})
        items = [_make_item("f1")]
        _enrich_items_from_structure(items, structure)
        assert items[0]["evidence"][0]["status"] == "verified"
        assert items[0]["evidence"][0]["verified"] is True
        assert not _is_taint_source(items[0])

    def test_axiom_with_verified_evidence(self):
        ev = Evidence(document="doc.py", quotes=["def bar():"], verified=True)
        ax = Axiom(name="a1", wff=True, origin=ev)
        structure = FakeStructure(graph={"a1": _make_node("a1", NodeKind.AXIOM, ax)})
        items = [_make_item("a1")]
        _enrich_items_from_structure(items, structure)
        assert items[0]["evidence"][0]["status"] == "verified"
        assert not _is_taint_source(items[0])

    def test_term_with_verified_evidence(self):
        ev = Evidence(document="doc.py", quotes=["x = 1"], verified=True)
        term = Term(name="t1", definition=42, origin=ev)
        structure = FakeStructure(graph={"t1": _make_node("t1", NodeKind.TERM_COMP, term)})
        items = [_make_item("t1")]
        _enrich_items_from_structure(items, structure)
        assert items[0]["evidence"][0]["status"] == "verified"
        assert not _is_taint_source(items[0])


class TestEvidenceStatusManual:
    """Evidence with verify_manual=True (but verified=False) → status 'manual'."""

    def test_term_verify_manual(self):
        ev = Evidence(document="manual", quotes=[], explanation="hand-checked", verify_manual=True)
        term = Term(name="t1", definition=42, origin=ev)
        structure = FakeStructure(graph={"t1": _make_node("t1", NodeKind.TERM_COMP, term)})
        items = [_make_item("t1")]
        _enrich_items_from_structure(items, structure)
        assert items[0]["evidence"][0]["status"] == "manual"
        assert items[0]["evidence"][0]["verified"] is False
        assert not _is_taint_source(items[0])

    def test_fact_verify_manual(self):
        ev = Evidence(document="manual", quotes=[], verify_manual=True)
        fact = Fact(name="f1", wff=True, origin=ev)
        structure = FakeStructure(graph={"f1": _make_node("f1", NodeKind.FACT, fact)})
        items = [_make_item("f1")]
        _enrich_items_from_structure(items, structure)
        assert items[0]["evidence"][0]["status"] == "manual"
        assert not _is_taint_source(items[0])


class TestEvidenceStatusUnverified:
    """Evidence with verified=False and verify_manual=False → status 'unverified'."""

    def test_evidence_not_verified(self):
        ev = Evidence(document="doc.py", quotes=["no match here"])
        fact = Fact(name="f1", wff=True, origin=ev)
        structure = FakeStructure(graph={"f1": _make_node("f1", NodeKind.FACT, fact)})
        items = [_make_item("f1")]
        _enrich_items_from_structure(items, structure)
        assert items[0]["evidence"][0]["status"] == "unverified"
        assert items[0]["evidence"][0]["verified"] is False
        assert _is_taint_source(items[0])

    def test_string_origin_without_verify_manual(self):
        """String :origin that was NOT verify-manual'd → 'unverified' and tainted."""
        term = Term(name="t1", definition=99, origin="some rationale but never verified")
        structure = FakeStructure(graph={"t1": _make_node("t1", NodeKind.TERM_COMP, term)})
        items = [_make_item("t1")]
        _enrich_items_from_structure(items, structure)
        assert items[0]["evidence"][0]["status"] == "unverified"
        assert items[0]["evidence"][0]["doc"] == "some rationale but never verified"
        assert _is_taint_source(items[0])


class TestEvidenceStatusDerived:
    """Theorems and derived origins → status 'derived'."""

    def test_theorem(self):
        thm = Theorem(name="th1", wff=True, derivation=["f1"])
        structure = FakeStructure(graph={"th1": _make_node("th1", NodeKind.THEOREM, thm)})
        items = [_make_item("th1")]
        _enrich_items_from_structure(items, structure)
        assert items[0]["evidence"][0]["status"] == "derived"
        assert not _is_taint_source(items[0])

    def test_derived_origin_string(self):
        fact = Fact(name="f1", wff=True, origin="derived")
        structure = FakeStructure(graph={"f1": _make_node("f1", NodeKind.FACT, fact)})
        items = [_make_item("f1")]
        _enrich_items_from_structure(items, structure)
        assert items[0]["evidence"][0]["status"] == "derived"
        assert not _is_taint_source(items[0])


class TestEvidenceEdgeCases:
    """Edge cases: no atom, no origin, empty origin."""

    def test_no_atom(self):
        """No atom → no evidence → taint source."""
        node = Node(name="n1", kind=NodeKind.FACT, value=True, inputs=[], atom=None)
        structure = FakeStructure(graph={"n1": node})
        items = [_make_item("n1")]
        _enrich_items_from_structure(items, structure)
        assert items[0]["evidence"] == []
        assert _is_taint_source(items[0])

    def test_empty_string_origin(self):
        """Empty string origin → no evidence → taint source."""
        fact = Fact(name="f1", wff=True, origin="")
        structure = FakeStructure(graph={"f1": _make_node("f1", NodeKind.FACT, fact)})
        items = [_make_item("f1")]
        _enrich_items_from_structure(items, structure)
        assert items[0]["evidence"] == []
        assert _is_taint_source(items[0])

    def test_none_origin(self):
        """None origin → no evidence → taint source."""
        term = Term(name="t1", definition=42, origin=None)
        structure = FakeStructure(graph={"t1": _make_node("t1", NodeKind.TERM_COMP, term)})
        items = [_make_item("t1")]
        _enrich_items_from_structure(items, structure)
        assert items[0]["evidence"] == []
        assert _is_taint_source(items[0])

    def test_item_not_in_graph(self):
        """Item not in structure graph → no evidence → taint source."""
        structure = FakeStructure(graph={})
        items = [_make_item("missing")]
        _enrich_items_from_structure(items, structure)
        assert items[0]["evidence"] == []
        assert _is_taint_source(items[0])

    def test_verified_and_manual_both_true(self):
        """If both verified and verify_manual are True, status should be 'verified' (verified wins)."""
        ev = Evidence(document="doc.py", quotes=["x"], verified=True, verify_manual=True)
        fact = Fact(name="f1", wff=True, origin=ev)
        structure = FakeStructure(graph={"f1": _make_node("f1", NodeKind.FACT, fact)})
        items = [_make_item("f1")]
        _enrich_items_from_structure(items, structure)
        assert items[0]["evidence"][0]["status"] == "verified"
        assert not _is_taint_source(items[0])
