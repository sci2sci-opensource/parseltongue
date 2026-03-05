"""Tests for System serialization / deserialization (to_dict / from_dict)."""

import json
import unittest
from unittest.mock import patch

from .. import Evidence, Symbol, System, load_source
from ..atoms import to_sexp


def make_system(**kwargs):
    with patch("builtins.print"):
        return System(**kwargs)


def quiet(fn, *args, **kwargs):
    with patch("builtins.print"):
        return fn(*args, **kwargs)


def roundtrip(system: System) -> System:
    """Serialize and deserialize a system through JSON."""
    data = system.to_dict()
    json_str = json.dumps(data)
    return System.from_dict(json.loads(json_str))


# ==============================================================
# Basic round-trip
# ==============================================================


class TestBasicRoundtrip(unittest.TestCase):
    """to_dict -> JSON -> from_dict preserves all stores."""

    def test_empty_system(self):
        s = make_system()
        s2 = roundtrip(s)
        self.assertEqual(s2.terms, {})
        self.assertEqual(s2.facts, {})
        self.assertEqual(s2.axioms, {})
        self.assertEqual(s2.theorems, {})
        self.assertEqual(s2.diffs, {})

    def test_facts_preserved(self):
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact revenue 15 :origin "report")
            (fact margin 0.22 :origin "report")
        """,
        )
        s2 = roundtrip(s)
        self.assertEqual(s2.facts["revenue"].wff, 15)
        self.assertEqual(s2.facts["margin"].wff, 0.22)

    def test_terms_preserved(self):
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact revenue 15 :origin "test")
            (defterm double-revenue (* revenue 2) :origin "test")
        """,
        )
        s2 = roundtrip(s)
        self.assertIn("double-revenue", s2.terms)
        self.assertEqual(
            to_sexp(s2.terms["double-revenue"].definition),
            "(* revenue 2)",
        )

    def test_axioms_preserved(self):
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact revenue 15 :origin "test")
            (axiom positive-rev (> ?x 0) :origin "test")
        """,
        )
        s2 = roundtrip(s)
        self.assertIn("positive-rev", s2.axioms)
        self.assertEqual(
            to_sexp(s2.axioms["positive-rev"].wff),
            "(> ?x 0)",
        )

    def test_theorems_preserved(self):
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact x 5 :origin "test")
            (derive bounded (and (> x 0) (< x 100)) :using (x))
        """,
        )
        s2 = roundtrip(s)
        self.assertIn("bounded", s2.theorems)
        self.assertEqual(s2.theorems["bounded"].derivation, ["x"])

    def test_diffs_preserved(self):
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact rate-a 0.15 :origin "test")
            (fact rate-b 0.20 :origin "test")
            (diff d1 :replace rate-a :with rate-b)
        """,
        )
        s2 = roundtrip(s)
        self.assertIn("d1", s2.diffs)
        self.assertEqual(s2.diffs["d1"]["replace"], "rate-a")
        self.assertEqual(s2.diffs["d1"]["with"], "rate-b")

    def test_documents_preserved(self):
        s = make_system()
        s.documents["report"] = "Q3 revenue was $15M."
        s2 = roundtrip(s)
        self.assertEqual(s2.documents["report"], "Q3 revenue was $15M.")


# ==============================================================
# Evidence serialization
# ==============================================================

SAMPLE_DOC = "Q3 revenue was $15M. Margin improved to 22%. Growth formula applies."


class TestEvidenceSerialization(unittest.TestCase):
    """Evidence objects survive round-trip."""

    def test_evidence_on_fact(self):
        s = make_system()
        quiet(s.register_document, "report", SAMPLE_DOC)
        quiet(
            load_source,
            s,
            """
            (fact revenue 15
              :evidence (evidence "report"
                :quotes ("Q3 revenue was $15M")
                :explanation "revenue figure"))
        """,
        )
        s2 = roundtrip(s)
        origin = s2.facts["revenue"].origin
        self.assertIsInstance(origin, Evidence)
        self.assertEqual(origin.document, "report")
        self.assertEqual(origin.quotes, ["Q3 revenue was $15M"])

    def test_evidence_on_axiom(self):
        s = make_system()
        quiet(s.register_document, "report", SAMPLE_DOC)
        quiet(
            load_source,
            s,
            """
            (fact margin 22 :origin "test")
            (axiom positive-margin (> ?m 0)
              :evidence (evidence "report"
                :quotes ("Margin improved to 22%")
                :explanation "margin positive"))
        """,
        )
        s2 = roundtrip(s)
        origin = s2.axioms["positive-margin"].origin
        self.assertIsInstance(origin, Evidence)
        self.assertEqual(origin.document, "report")

    def test_evidence_on_term(self):
        s = make_system()
        quiet(s.register_document, "report", SAMPLE_DOC)
        quiet(
            load_source,
            s,
            """
            (defterm growth (+ 1 2)
              :evidence (evidence "report"
                :quotes ("Growth formula applies")
                :explanation "growth def"))
        """,
        )
        s2 = roundtrip(s)
        origin = s2.terms["growth"].origin
        self.assertIsInstance(origin, Evidence)
        self.assertEqual(origin.quotes, ["Growth formula applies"])

    def test_string_origin_preserved(self):
        s = make_system()
        quiet(load_source, s, '(fact x 42 :origin "manual entry")')
        s2 = roundtrip(s)
        self.assertEqual(s2.facts["x"].origin, "manual entry")


# ==============================================================
# S-expression serialization
# ==============================================================


class TestSexpSerialization(unittest.TestCase):
    """Symbol objects in definitions survive JSON round-trip."""

    def test_nested_sexp(self):
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (defterm growth (* (/ (- a b) b) 100) :origin "test")
        """,
        )
        s2 = roundtrip(s)
        self.assertEqual(
            to_sexp(s2.terms["growth"].definition),
            "(* (/ (- a b) b) 100)",
        )

    def test_symbols_are_symbols_after_roundtrip(self):
        s = make_system()
        quiet(load_source, s, '(defterm t (+ a b) :origin "test")')
        s2 = roundtrip(s)
        defn = s2.terms["t"].definition
        self.assertIsInstance(defn[0], Symbol)
        self.assertIsInstance(defn[1], Symbol)
        self.assertIsInstance(defn[2], Symbol)


# ==============================================================
# Env rebuild — the critical bug fix
# ==============================================================


class TestEnvRebuild(unittest.TestCase):
    """from_dict must rebuild env so evaluate/_resolve_value works."""

    def test_fact_values_in_env(self):
        s = make_system()
        quiet(load_source, s, '(fact rate 0.15 :origin "test")')
        s2 = roundtrip(s)
        self.assertEqual(s2.engine.env[Symbol("rate")], 0.15)

    def test_term_evaluated_in_env(self):
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact base 100 :origin "test")
            (defterm doubled (* base 2) :origin "test")
        """,
        )
        s2 = roundtrip(s)
        self.assertEqual(s2.engine.env[Symbol("doubled")], 200)

    def test_chained_terms_evaluated(self):
        """Term A depends on term B depends on fact — all resolve."""
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact x 10 :origin "test")
            (defterm y (+ x 5) :origin "test")
            (defterm z (* y 2) :origin "test")
        """,
        )
        s2 = roundtrip(s)
        self.assertEqual(s2.engine.env[Symbol("x")], 10)
        self.assertEqual(s2.engine.env[Symbol("y")], 15)
        self.assertEqual(s2.engine.env[Symbol("z")], 30)

    def test_axiom_definition_in_env(self):
        """Term definition populates env after round-trip."""
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact a 3 :origin "test")
            (defterm b (+ a 7) :origin "test")
        """,
        )
        s2 = roundtrip(s)
        self.assertEqual(s2.engine.env[Symbol("b")], 10)

    def test_forward_declared_term_not_in_env(self):
        """Term with no definition should not crash env rebuild."""
        s = make_system()
        quiet(load_source, s, '(defterm placeholder :origin "test")')
        s2 = roundtrip(s)
        self.assertNotIn(Symbol("placeholder"), s2.engine.env)


# ==============================================================
# eval_diff on deserialized system
# ==============================================================


class TestEvalDiffAfterRoundtrip(unittest.TestCase):
    """eval_diff must return evaluated numbers, not formulas."""

    def test_diff_returns_numbers(self):
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact standard-rate 0.15 :origin "test")
            (fact accel-rate 0.20 :origin "test")
            (diff d1 :replace standard-rate :with accel-rate)
        """,
        )
        s2 = roundtrip(s)
        result = s2.eval_diff("d1")
        self.assertEqual(result.value_a, 0.15)
        self.assertEqual(result.value_b, 0.20)

    def test_diff_with_computed_terms(self):
        """Diff where both sides are computed terms — values not formulas."""
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact base 100 :origin "test")
            (defterm bonus-a (* base 0.15) :origin "test")
            (defterm bonus-b (* base 0.20) :origin "test")
            (diff d1 :replace bonus-a :with bonus-b)
        """,
        )
        s2 = roundtrip(s)
        result = s2.eval_diff("d1")
        self.assertAlmostEqual(result.value_a, 15.0)
        self.assertAlmostEqual(result.value_b, 20.0)

    def test_diff_divergences_are_numbers(self):
        """Divergences in dependent terms must be evaluated numbers."""
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact rate-a 10 :origin "test")
            (fact rate-b 20 :origin "test")
            (defterm result (* rate-a 3) :origin "test")
            (diff d1 :replace rate-a :with rate-b)
        """,
        )
        s2 = roundtrip(s)
        result = s2.eval_diff("d1")
        self.assertEqual(result.value_a, 10)
        self.assertEqual(result.value_b, 20)
        self.assertIn("result", result.divergences)
        self.assertEqual(result.divergences["result"], [30, 60])

    def test_diff_provenance_has_numbers(self):
        """system.provenance() on deserialized system has numeric values."""
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact rate-a 15 :origin "test")
            (fact rate-b 20 :origin "test")
            (diff d1 :replace rate-a :with rate-b)
        """,
        )
        s2 = roundtrip(s)
        prov = s2.provenance("d1")
        self.assertEqual(prov["value_a"], 15)
        self.assertEqual(prov["value_b"], 20)
        self.assertIsInstance(prov["value_a"], (int, float))
        self.assertIsInstance(prov["value_b"], (int, float))

    def test_complex_chain_diff_provenance(self):
        """Multi-level term chain: diff provenance shows numbers, not formulas."""
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact revenue 1000 :origin "test")
            (fact prior-revenue 800 :origin "test")
            (defterm growth (* (/ (- revenue prior-revenue) prior-revenue) 100)
              :origin "test")
            (fact alt-revenue 1200 :origin "test")
            (diff check :replace revenue :with alt-revenue)
        """,
        )
        s2 = roundtrip(s)
        result = s2.eval_diff("check")
        self.assertEqual(result.value_a, 1000)
        self.assertEqual(result.value_b, 1200)
        self.assertIn("growth", result.divergences)
        # original: (1000-800)/800*100 = 25.0
        # substituted: (1200-800)/800*100 = 50.0
        self.assertAlmostEqual(result.divergences["growth"][0], 25.0)
        self.assertAlmostEqual(result.divergences["growth"][1], 50.0)

        prov = s2.provenance("check")
        self.assertIsInstance(prov["value_a"], (int, float))
        self.assertIsInstance(prov["value_b"], (int, float))


# ==============================================================
# Consistency on deserialized system
# ==============================================================


class TestConsistencyAfterRoundtrip(unittest.TestCase):
    """consistency() must work on deserialized systems."""

    def test_consistent_system_stays_consistent(self):
        s = make_system()
        quiet(s.register_document, "report", SAMPLE_DOC)
        quiet(
            load_source,
            s,
            """
            (fact revenue 15
              :evidence (evidence "report"
                :quotes ("Q3 revenue was $15M")
                :explanation "revenue figure"))
        """,
        )
        s2 = roundtrip(s)
        report = s2.consistency()
        self.assertTrue(report.consistent)

    def test_resolve_value_uses_env(self):
        """_resolve_value on deserialized system returns numbers."""
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact x 42 :origin "test")
            (defterm y (+ x 8) :origin "test")
        """,
        )
        s2 = roundtrip(s)
        self.assertEqual(s2.engine._resolve_value("x"), 42)
        self.assertEqual(s2.engine._resolve_value("y"), 50)


# ==============================================================
# Legacy format — facts serialized with "value" key (pre-Fact)
# ==============================================================


def _legacy_serialize_fact(fact):
    """Old _serialize_fact that used 'value' key and handled raw dicts."""
    from ..serialization import serialize_origin as _serialize_origin
    from ..serialization import serialize_sexp as _serialize_sexp

    if isinstance(fact, dict):
        result = dict(fact)
        if "origin" in result:
            result["origin"] = _serialize_origin(result["origin"])
        if "value" in result:
            result["value"] = _serialize_sexp(result["value"])
        return result
    return {"value": _serialize_sexp(fact)}


def _legacy_serialize_system(system: System) -> dict:
    """Serialize a system using the old fact format (value key)."""

    data = system.to_dict()
    # Re-serialize facts using legacy format: convert Fact objects to old dicts
    legacy_facts = {}
    for name, fact in system.facts.items():
        legacy_facts[name] = _legacy_serialize_fact({"value": fact.wff, "origin": fact.origin})
    data["facts"] = legacy_facts
    return data


class TestLegacyFactFormat(unittest.TestCase):
    """System.from_dict must restore facts from the old {"value": ...} format."""

    def _roundtrip_legacy(self, system: System) -> System:
        """Serialize with legacy format, deserialize with current from_dict."""
        data = _legacy_serialize_system(system)
        json_str = json.dumps(data)
        return System.from_dict(json.loads(json_str))

    def test_numeric_fact(self):
        s = make_system()
        quiet(load_source, s, '(fact revenue 15 :origin "report")')
        s2 = self._roundtrip_legacy(s)
        self.assertEqual(s2.facts["revenue"].wff, 15)
        self.assertEqual(s2.facts["revenue"].origin, "report")
        self.assertEqual(s2.facts["revenue"].name, "revenue")

    def test_string_fact(self):
        s = make_system()
        quiet(load_source, s, '(fact algo "sha256" :origin "spec")')
        s2 = self._roundtrip_legacy(s)
        self.assertEqual(s2.facts["algo"].wff, "sha256")

    def test_boolean_fact(self):
        s = make_system()
        quiet(load_source, s, '(fact flag true :origin "config")')
        s2 = self._roundtrip_legacy(s)
        self.assertIs(s2.facts["flag"].wff, True)

    def test_float_fact(self):
        s = make_system()
        quiet(load_source, s, '(fact margin 0.22 :origin "report")')
        s2 = self._roundtrip_legacy(s)
        self.assertAlmostEqual(s2.facts["margin"].wff, 0.22)

    def test_fact_in_env(self):
        """Legacy-restored fact values are placed in env for evaluation."""
        s = make_system()
        quiet(load_source, s, '(fact x 42 :origin "test")')
        s2 = self._roundtrip_legacy(s)
        self.assertEqual(s2.engine.env[Symbol("x")], 42)

    def test_multiple_facts(self):
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact a 10 :origin "test")
            (fact b 20 :origin "test")
        """,
        )
        s2 = self._roundtrip_legacy(s)
        self.assertEqual(s2.facts["a"].wff, 10)
        self.assertEqual(s2.facts["b"].wff, 20)

    def test_evidence_origin(self):
        """Evidence objects survive legacy serialization round-trip."""
        s = make_system()
        quiet(s.register_document, "report", SAMPLE_DOC)
        quiet(
            load_source,
            s,
            """
            (fact revenue 15
              :evidence (evidence "report"
                :quotes ("Q3 revenue was $15M")
                :explanation "revenue figure"))
        """,
        )
        s2 = self._roundtrip_legacy(s)
        origin = s2.facts["revenue"].origin
        self.assertIsInstance(origin, Evidence)
        self.assertEqual(origin.document, "report")
        self.assertEqual(origin.quotes, ["Q3 revenue was $15M"])

    def test_eval_diff_on_legacy(self):
        """eval_diff works after restoring from legacy format."""
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact rate-a 0.15 :origin "test")
            (fact rate-b 0.20 :origin "test")
            (diff d1 :replace rate-a :with rate-b)
        """,
        )
        s2 = self._roundtrip_legacy(s)
        result = s2.eval_diff("d1")
        self.assertAlmostEqual(result.value_a, 0.15)
        self.assertAlmostEqual(result.value_b, 0.20)

    def test_term_depends_on_legacy_fact(self):
        """A term referencing a legacy fact evaluates correctly."""
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact base 100 :origin "test")
            (defterm doubled (* base 2) :origin "test")
        """,
        )
        s2 = self._roundtrip_legacy(s)
        self.assertEqual(s2.engine.env[Symbol("doubled")], 200)

    def test_theorem_on_legacy_facts(self):
        """Theorems derived from legacy facts are preserved."""
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact x 5 :origin "test")
            (derive bounded (> x 0) :using (x))
        """,
        )
        s2 = self._roundtrip_legacy(s)
        self.assertIn("bounded", s2.theorems)
        self.assertEqual(s2.theorems["bounded"].derivation, ["x"])

    def test_consistency_on_legacy(self):
        """Consistency check works on a system restored from legacy format."""
        s = make_system()
        quiet(s.register_document, "report", SAMPLE_DOC)
        quiet(
            load_source,
            s,
            """
            (fact revenue 15
              :evidence (evidence "report"
                :quotes ("Q3 revenue was $15M")
                :explanation "revenue figure"))
        """,
        )
        s2 = self._roundtrip_legacy(s)
        report = s2.consistency()
        self.assertTrue(report.consistent)

    def test_legacy_payload_uses_value_key(self):
        """Verify the legacy serializer actually emits 'value', not 'wff'."""
        s = make_system()
        quiet(load_source, s, '(fact x 42 :origin "test")')
        data = _legacy_serialize_system(s)
        self.assertIn("value", data["facts"]["x"])
        self.assertNotIn("wff", data["facts"]["x"])


class TestNewFactFormat(unittest.TestCase):
    """Verify the new {"wff": ...} format serializes and deserializes correctly."""

    def test_new_format_uses_wff_key(self):
        """Current serializer emits 'wff', not 'value'."""
        s = make_system()
        quiet(load_source, s, '(fact x 42 :origin "test")')
        data = s.to_dict()
        self.assertIn("wff", data["facts"]["x"])
        self.assertNotIn("value", data["facts"]["x"])

    def test_new_format_roundtrips(self):
        s = make_system()
        quiet(load_source, s, '(fact x 42 :origin "test")')
        s2 = roundtrip(s)
        self.assertEqual(s2.facts["x"].wff, 42)
        self.assertEqual(s2.facts["x"].name, "x")

    def test_wff_takes_precedence_over_value(self):
        """If both keys are present, wff wins (forward compat)."""
        data = {"facts": {"x": {"wff": 100, "value": 999, "origin": "test"}}}
        s = System.from_dict(data)
        self.assertEqual(s.facts["x"].wff, 100)


if __name__ == "__main__":
    unittest.main()
