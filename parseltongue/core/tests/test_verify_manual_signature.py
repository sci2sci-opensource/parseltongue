"""Tests for verify_manual signature — full chain from System to rendered Screen.

Verifies the complete pipeline:
  System.verify_manual(name, signature)
  → Evidence gets signature + [Signed: X] in explanation
  → ConsistencyReport.warnings has details dict
  → details survives serialization round-trip
  → LocatedConsistencyReport passes details through
  → Screen.from_report stores details on ScreenItem.detail
  → Screen.summary() renders detail text
"""

from __future__ import annotations

import unittest

from parseltongue.core.atoms import Evidence, Symbol
from parseltongue.core.engine import ConsistencyWarning, IssueType, WarningType
from parseltongue.core.system import System


def _make_system(*facts, axioms=None, terms=None):
    """Build a System with facts, axioms, terms. Each fact is (name, value, origin)."""
    s = System("test")
    for name, value, origin in facts:
        s.engine.set_fact(name, value, origin)
    for name, wff, origin in axioms or []:
        s.engine.introduce_axiom(name, wff, origin)
    for name, defn, origin in terms or []:
        s.engine.introduce_term(name, defn, origin)
    return s


class TestSignatureOnEvidence(unittest.TestCase):
    """verify_manual stores signature on Evidence and appends to explanation."""

    def test_signature_stored(self):
        s = _make_system(("x", 42, Evidence(document="doc", quotes=["q"], explanation="orig")))
        s.verify_manual("x", signature="Alice")
        origin = s.engine.facts["x"].origin
        self.assertEqual(origin.signature, "Alice")
        self.assertTrue(origin.verify_manual)

    def test_signature_in_explanation(self):
        s = _make_system(("x", 42, Evidence(document="doc", quotes=["q"], explanation="orig")))
        s.verify_manual("x", signature="Claude")
        self.assertIn("[Signed: Claude]", s.engine.facts["x"].origin.explanation)

    def test_default_signature_is_system(self):
        s = _make_system(("x", 42, Evidence(document="doc", quotes=["q"], explanation="orig")))
        s.verify_manual("x")
        origin = s.engine.facts["x"].origin
        self.assertEqual(origin.signature, "system")
        self.assertIn("[Signed: system]", origin.explanation)

    def test_string_origin_becomes_evidence(self):
        s = _make_system(("x", 42, "business rule: margin > 60%"))
        s.verify_manual("x", signature="Claude")
        origin = s.engine.facts["x"].origin
        self.assertIsInstance(origin, Evidence)
        self.assertEqual(origin.signature, "Claude")
        self.assertIn("business rule", origin.explanation)
        self.assertIn("[Signed: Claude]", origin.explanation)

    def test_empty_explanation(self):
        s = _make_system(("x", 42, Evidence(document="doc", quotes=["q"], explanation="")))
        s.verify_manual("x", signature="Bob")
        self.assertEqual(s.engine.facts["x"].origin.explanation, "[Signed: Bob]")

    def test_axiom_signature(self):
        s = _make_system(axioms=[("ax1", [Symbol("="), Symbol("?x"), Symbol("?x")], "self-evident")])
        s.verify_manual("ax1", signature="Claude")
        self.assertEqual(s.engine.axioms["ax1"].origin.signature, "Claude")

    def test_term_signature(self):
        s = _make_system(terms=[("t1", None, "primitive")])
        s.verify_manual("t1", signature="Alice")
        self.assertEqual(s.engine.terms["t1"].origin.signature, "Alice")


class TestSymbolTermEvidence(unittest.TestCase):
    """A defterm remains an independently evidenced declaration."""

    @staticmethod
    def _no_evidence_names(system: System) -> set[str]:
        report = system.consistency()
        return {name for issue in report.issues if issue.type == IssueType.NO_EVIDENCE for name, _origin in issue.items}

    def test_user_symbol_term_keeps_its_own_unsupported_origin(self):
        s = _make_system(
            ("grounded", True, Evidence(document="manual", quotes=[], verify_manual=True)),
            terms=[("unsupported", Symbol("grounded"), "user assertion without evidence")],
        )

        self.assertIn("unsupported", self._no_evidence_names(s))


class TestFullChainToScreen(unittest.TestCase):
    """Full pipeline: System → verify_manual → consistency → Screen → summary."""

    def _build_screen(self, facts, signatures):
        """Create system, verify facts, return Screen."""
        from parseltongue.core.inspect.screen import Screen
        from parseltongue.core.loader.lazy_loader import LocatedConsistencyReport

        s = _make_system(*facts)
        for name, sig in signatures:
            s.verify_manual(name, signature=sig)

        report = s.consistency()
        lc = LocatedConsistencyReport(report=report, _engine=s.engine)
        return Screen.from_report(lc), report

    def test_warning_details_in_report(self):
        """ConsistencyReport.warnings has details with signature."""
        _, report = self._build_screen(
            [("x", 42, "business rule: threshold")],
            [("x", "Claude")],
        )
        manual = [w for w in report.warnings if w.type == WarningType.MANUALLY_VERIFIED]
        self.assertEqual(len(manual), 1)
        w = manual[0]
        self.assertIn("x", w.details)
        self.assertIn("[Signed: Claude]", w.details["x"])
        self.assertIn("business rule", w.details["x"])

    def test_screen_item_detail_not_just_name(self):
        """ScreenItem.detail should contain origin info, not just the name."""
        dx, _ = self._build_screen(
            [("myval", 10, "assumed threshold")],
            [("myval", "Claude")],
        )
        manual = [w for w in dx.warnings() if w.type == "manually_verified"]
        self.assertTrue(manual, "Expected manually_verified warnings")
        item = manual[0]
        self.assertNotEqual(item.detail, item.name)
        self.assertIn("[Signed: Claude]", str(item.detail))

    def test_screen_item_detail_has_origin_text(self):
        """ScreenItem.detail should include the original origin string."""
        dx, _ = self._build_screen(
            [("threshold", 60, "VC standard: gross margin > 60%")],
            [("threshold", "Alice")],
        )
        manual = [w for w in dx.warnings() if w.type == "manually_verified"]
        self.assertIn("VC standard", str(manual[0].detail))

    def test_summary_renders_detail(self):
        """Screen.summary() should include detail text for warnings."""
        dx, _ = self._build_screen(
            [("x", 42, "business rule: margin check")],
            [("x", "Claude")],
        )
        summary = dx.summary()
        self.assertIn("[Signed: Claude]", summary)

    def test_multiple_facts_different_signatures(self):
        """Multiple facts verified by different signers."""
        dx, report = self._build_screen(
            [
                ("a", 1, "rule A"),
                ("b", 2, "rule B"),
            ],
            [("a", "Claude"), ("b", "Alice")],
        )
        manual = [w for w in report.warnings if w.type == WarningType.MANUALLY_VERIFIED]
        self.assertEqual(len(manual), 1)
        w = manual[0]
        self.assertIn("[Signed: Claude]", w.details["a"])
        self.assertIn("[Signed: Alice]", w.details["b"])

        # Screen items
        items = [i for i in dx.warnings() if i.type == "manually_verified"]
        details = {i.name: i.detail for i in items}
        self.assertIn("[Signed: Claude]", str(details["a"]))
        self.assertIn("[Signed: Alice]", str(details["b"]))


class TestWarningDetailsSerialization(unittest.TestCase):
    """ConsistencyWarning details survive serialization round-trip."""

    def test_round_trip_with_details(self):
        w = ConsistencyWarning(
            type=WarningType.MANUALLY_VERIFIED,
            items=["x", "y"],
            details={"x": "explanation=rule [Signed: Claude]", "y": "no origin"},
        )
        d = w.to_dict()
        self.assertIn("details", d)
        w2 = ConsistencyWarning.from_dict(d)
        self.assertEqual(w2.details, w.details)

    def test_round_trip_without_details(self):
        w = ConsistencyWarning(type=WarningType.MANUALLY_VERIFIED, items=["x"])
        d = w.to_dict()
        w2 = ConsistencyWarning.from_dict(d)
        self.assertEqual(w2.details, {})

    def test_full_report_round_trip(self):
        """Full ConsistencyReport serialization preserves warning details."""
        s = _make_system(("x", 42, "some rule"))
        s.verify_manual("x", signature="Claude")
        report = s.consistency()

        d = report.to_dict()
        from parseltongue.core.engine import ConsistencyReport

        report2 = ConsistencyReport.from_dict(d)

        manual = [w for w in report2.warnings if w.type == WarningType.MANUALLY_VERIFIED]
        self.assertTrue(manual)
        self.assertIn("[Signed: Claude]", manual[0].details.get("x", ""))


class TestScreenSerializationPreservesDetail(unittest.TestCase):
    """Screen serialization round-trip preserves detail from warnings."""

    def test_screen_round_trip(self):
        from parseltongue.core.inspect.screen import Screen
        from parseltongue.core.loader.lazy_loader import LocatedConsistencyReport

        s = _make_system(("x", 42, "rule"))
        s.verify_manual("x", signature="Claude")
        report = s.consistency()
        lc = LocatedConsistencyReport(report=report, _engine=s.engine)
        dx = Screen.from_report(lc)

        # Round-trip
        d = dx.to_dict()
        dx2 = Screen.from_dict(d)

        manual = [w for w in dx2.warnings() if w.type == "manually_verified"]
        self.assertTrue(manual)
        self.assertIn("[Signed: Claude]", str(manual[0].detail))


class TestLoaderEffectSignature(unittest.TestCase):
    """The verify-manual loader effect accepts optional signature."""

    def test_effect_with_signature(self):
        s = _make_system(("f1", True, "test origin"))
        s.verify_manual("f1", signature="Alice")
        self.assertEqual(s.engine.facts["f1"].origin.signature, "Alice")

    def test_effect_default_signature(self):
        s = _make_system(("f1", True, "test origin"))
        s.verify_manual("f1")
        self.assertEqual(s.engine.facts["f1"].origin.signature, "system")


if __name__ == "__main__":
    unittest.main()
