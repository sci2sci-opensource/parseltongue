"""Tests for Parseltongue DSL loader (load_source / _execute_directive)."""

import unittest
from unittest.mock import patch

from .. import Evidence, Symbol, System, load_source

SAMPLE_DOC = "Revenue growth target for FY2024: 10%. Q3 revenue was $15M."


def make_system(**kwargs):
    with patch("builtins.print"):
        return System(**kwargs)


def quiet(fn, *args, **kwargs):
    with patch("builtins.print"):
        return fn(*args, **kwargs)


class TestFactDirective(unittest.TestCase):
    def test_fact_with_origin(self):
        s = make_system()
        quiet(load_source, s, '(fact revenue 15 :origin "Q3 report")')
        self.assertIn("revenue", s.facts)
        self.assertEqual(s.facts["revenue"]["value"], 15)
        self.assertEqual(s.facts["revenue"]["origin"], "Q3 report")

    def test_fact_with_evidence(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        quiet(
            load_source,
            s,
            """
            (fact rev 15
              :evidence (evidence "Doc"
                :quotes ("Q3 revenue was $15M")
                :explanation "revenue figure"))
        """,
        )
        self.assertIn("rev", s.facts)
        origin = s.facts["rev"]["origin"]
        self.assertIsInstance(origin, Evidence)
        self.assertEqual(origin.document, "Doc")

    def test_fact_float_value(self):
        s = make_system()
        quiet(load_source, s, '(fact rate 0.15 :origin "test")')
        self.assertAlmostEqual(s.facts["rate"]["value"], 0.15)

    def test_fact_boolean_value(self):
        s = make_system()
        quiet(load_source, s, '(fact flag true :origin "test")')
        self.assertIs(s.facts["flag"]["value"], True)

    def test_fact_enters_env(self):
        s = make_system()
        quiet(load_source, s, '(fact x 42 :origin "test")')
        self.assertEqual(s.evaluate(Symbol("x")), 42)

    def test_fact_evidence_verified(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        quiet(
            load_source,
            s,
            """
            (fact rev 15
              :evidence (evidence "Doc"
                :quotes ("Q3 revenue was $15M")
                :explanation "exact match"))
        """,
        )
        self.assertTrue(s.facts["rev"]["origin"].verified)

    def test_fact_evidence_unverified(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        quiet(
            load_source,
            s,
            """
            (fact bad 999
              :evidence (evidence "Doc"
                :quotes ("This quote is completely fabricated")
                :explanation "no match"))
        """,
        )
        self.assertFalse(s.facts["bad"]["origin"].verified)

    def test_fact_evidence_multiple_quotes(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        quiet(
            load_source,
            s,
            """
            (fact x 10
              :evidence (evidence "Doc"
                :quotes ("Revenue growth target for FY2024: 10%"
                         "Q3 revenue was $15M")
                :explanation "two quotes"))
        """,
        )
        origin = s.facts["x"]["origin"]
        self.assertEqual(len(origin.quotes), 2)
        self.assertTrue(origin.verified)


class TestAxiomDirective(unittest.TestCase):
    def test_axiom(self):
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        quiet(load_source, s, '(axiom a1 (> x 0) :origin "test")')
        self.assertIn("a1", s.axioms)

    def test_axiom_stores_wff(self):
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        quiet(load_source, s, '(axiom a1 (> x 0) :origin "test")')
        ax = s.axioms["a1"]
        self.assertEqual(ax.wff, [Symbol(">"), Symbol("x"), 0])
        self.assertEqual(ax.origin, "test")

    def test_axiom_with_evidence(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        quiet(s.set_fact, "x", 5, "test")
        quiet(
            load_source,
            s,
            """
            (axiom a2 (> x 0)
              :evidence (evidence "Doc"
                :quotes ("Revenue growth target for FY2024: 10%")
                :explanation "test"))
        """,
        )
        self.assertIsInstance(s.axioms["a2"].origin, Evidence)

    def test_axiom_compound_wff(self):
        s = make_system()
        quiet(s.set_fact, "a", 5, "test")
        quiet(s.set_fact, "b", 3, "test")
        quiet(load_source, s, '(axiom a1 (= (+ a b) 8) :origin "test")')
        self.assertIn("a1", s.axioms)

    def test_axiom_default_origin(self):
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        quiet(load_source, s, "(axiom a1 (> x 0))")
        self.assertEqual(s.axioms["a1"].origin, "unknown")


class TestDeftermDirective(unittest.TestCase):
    def test_defterm(self):
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 20, "test")
        quiet(load_source, s, '(defterm total (+ a b) :origin "test")')
        self.assertIn("total", s.terms)
        result = s.evaluate(s.terms["total"].definition)
        self.assertEqual(result, 30)

    def test_defterm_with_evidence(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        quiet(s.set_fact, "a", 10, "test")
        quiet(
            load_source,
            s,
            """
            (defterm double_a (* a 2)
              :evidence (evidence "Doc"
                :quotes ("Revenue growth target for FY2024: 10%")
                :explanation "test"))
        """,
        )
        self.assertIsInstance(s.terms["double_a"].origin, Evidence)

    def test_defterm_auto_resolves_as_symbol(self):
        s = make_system()
        quiet(s.set_fact, "x", 3, "test")
        quiet(load_source, s, '(defterm doubled (* x 2) :origin "test")')
        self.assertEqual(s.evaluate(Symbol("doubled")), 6)

    def test_defterm_with_if(self):
        s = make_system()
        quiet(s.set_fact, "score", 85, "test")
        quiet(
            load_source,
            s,
            """
            (defterm grade
                (if (> score 90) "A" "B")
                :origin "test")
        """,
        )
        self.assertEqual(s.evaluate(s.terms["grade"].definition), "B")

    def test_defterm_nested_expression(self):
        s = make_system()
        quiet(s.set_fact, "a", 2, "test")
        quiet(s.set_fact, "b", 3, "test")
        quiet(s.set_fact, "c", 4, "test")
        quiet(load_source, s, '(defterm expr (+ (* a b) c) :origin "test")')
        self.assertEqual(s.evaluate(s.terms["expr"].definition), 10)

    def test_defterm_references_other_term(self):
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        quiet(
            load_source,
            s,
            """
            (defterm step1 (+ x 1) :origin "test")
            (defterm step2 (* step1 2) :origin "test")
        """,
        )
        self.assertEqual(s.evaluate(Symbol("step2")), 12)


class TestDeriveDirective(unittest.TestCase):
    def test_derive(self):
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        quiet(s.verify_manual, "x")
        quiet(load_source, s, "(derive d1 (> x 0) :using (x))")
        self.assertIn("d1", s.theorems)
        self.assertEqual(s.theorems["d1"].derivation, ["x"])

    def test_derive_multiple_sources(self):
        s = make_system()
        quiet(s.set_fact, "a", 5, "test")
        quiet(s.set_fact, "b", 3, "test")
        quiet(s.verify_manual, "a")
        quiet(s.verify_manual, "b")
        quiet(load_source, s, "(derive d1 (> a b) :using (a b))")
        self.assertEqual(s.theorems["d1"].derivation, ["a", "b"])

    def test_derive_from_fact_and_axiom(self):
        s = make_system()
        quiet(s.set_fact, "x", 10, "test")
        quiet(s.verify_manual, "x")
        quiet(s.introduce_axiom, "ax1", [Symbol(">"), Symbol("x"), 0], "test")
        quiet(s.verify_manual, "ax1")
        quiet(load_source, s, "(derive d1 (> x 0) :using (x ax1))")
        self.assertEqual(s.theorems["d1"].derivation, ["x", "ax1"])

    def test_derive_compound_wff(self):
        s = make_system()
        quiet(s.set_fact, "a", 3, "test")
        quiet(s.set_fact, "b", 7, "test")
        quiet(s.verify_manual, "a")
        quiet(s.verify_manual, "b")
        quiet(load_source, s, "(derive d1 (= (+ a b) 10) :using (a b))")
        self.assertIn("d1", s.theorems)


class TestDiffDirective(unittest.TestCase):
    def test_diff(self):
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 20, "test")
        quiet(load_source, s, "(diff d1 :replace a :with b)")
        self.assertIn("d1", s.diffs)
        self.assertEqual(s.diffs["d1"]["replace"], "a")
        self.assertEqual(s.diffs["d1"]["with"], "b")

    def test_diff_evaluates_correctly(self):
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 20, "test")
        quiet(s.introduce_term, "t", [Symbol("+"), Symbol("a"), 1], "test")
        quiet(load_source, s, "(diff d1 :replace a :with b)")
        result = s.eval_diff("d1")
        self.assertFalse(result.empty)
        self.assertIn("t", result.divergences)
        self.assertEqual(result.divergences["t"], [11, 21])


class TestMultipleDirectives(unittest.TestCase):
    def test_multiple_in_one_source(self):
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact x 10 :origin "test")
            (fact y 20 :origin "test")
        """,
        )
        self.assertIn("x", s.facts)
        self.assertIn("y", s.facts)
        self.assertEqual(s.facts["x"]["value"], 10)
        self.assertEqual(s.facts["y"]["value"], 20)

    def test_comments_ignored(self):
        s = make_system()
        quiet(
            load_source,
            s,
            """
            ;; This is a comment
            (fact x 10 :origin "test")
            ;; Another comment
            (fact y 20 :origin "test")
        """,
        )
        self.assertIn("x", s.facts)
        self.assertIn("y", s.facts)

    def test_mixed_directives(self):
        s = make_system()
        quiet(
            load_source,
            s,
            """
            (fact a 5 :origin "test")
            (fact b 10 :origin "test")
            (defterm sum_ab (+ a b) :origin "test")
            (diff d1 :replace a :with b)
        """,
        )
        self.assertIn("a", s.facts)
        self.assertIn("sum_ab", s.terms)
        self.assertIn("d1", s.diffs)


class TestBindDirective(unittest.TestCase):
    def test_derive_with_bind(self):
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        quiet(s.verify_manual, "x")
        quiet(s.introduce_axiom, "add-id", [Symbol("="), [Symbol("+"), Symbol("?n"), 0], Symbol("?n")], "test")
        quiet(s.verify_manual, "add-id")
        quiet(load_source, s, "(derive d1 add-id :bind ((?n x)) :using (x add-id))")
        self.assertIn("d1", s.theorems)
        self.assertEqual(s.theorems["d1"].derivation, ["x", "add-id"])

    def test_defterm_with_bind(self):
        s = make_system()
        quiet(s.introduce_term, "sum-template", [Symbol("+"), Symbol("?a"), Symbol("?b")], "test")
        quiet(s.set_fact, "x", 3, "test")
        quiet(s.set_fact, "y", 7, "test")
        quiet(load_source, s, '(defterm total sum-template :bind ((?a x) (?b y)) :origin "test")')
        self.assertIn("total", s.terms)
        result = s.evaluate(s.terms["total"].definition)
        self.assertEqual(result, 10)

    def test_axiom_with_bind(self):
        s = make_system()
        quiet(s.introduce_axiom, "add-id", [Symbol("="), [Symbol("+"), Symbol("?n"), 0], Symbol("?n")], "test")
        quiet(s.set_fact, "x", 5, "test")
        quiet(load_source, s, '(axiom ground-id add-id :bind ((?n x)) :origin "test")')
        self.assertIn("ground-id", s.axioms)
        # The WFF should be the instantiated version
        wff = s.axioms["ground-id"].wff
        self.assertEqual(wff, [Symbol("="), [Symbol("+"), Symbol("x"), 0], Symbol("x")])

    def test_derive_with_bind_and_evidence(self):
        s = make_system()
        quiet(s.register_document, "Doc", SAMPLE_DOC)
        quiet(s.set_fact, "rev", 15, "test")
        quiet(s.verify_manual, "rev")
        quiet(s.introduce_axiom, "gt-zero", [Symbol(">"), Symbol("?x"), 0], "test")
        quiet(s.verify_manual, "gt-zero")
        quiet(load_source, s, "(derive d1 gt-zero :bind ((?x rev)) :using (rev gt-zero))")
        self.assertIn("d1", s.theorems)


class TestDefaultOrigin(unittest.TestCase):
    def test_fact_no_origin_defaults_to_unknown(self):
        s = make_system()
        quiet(load_source, s, "(fact x 10)")
        self.assertEqual(s.facts["x"]["origin"], "unknown")


if __name__ == "__main__":
    unittest.main()
