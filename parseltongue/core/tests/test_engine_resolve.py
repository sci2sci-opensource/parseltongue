"""Tests for Engine._resolve_value — symbol resolution across all stores."""

import logging
import unittest

from .. import Symbol, System, load_source


def quiet(fn, *args, **kwargs):
    logging.disable(logging.CRITICAL)
    try:
        return fn(*args, **kwargs)
    finally:
        logging.disable(logging.NOTSET)


class TestResolveValue(unittest.TestCase):
    """_resolve_value must find symbols in env, terms, facts, theorems, and axioms."""

    def setUp(self):
        self.s = System()

    def test_resolve_fact(self):
        quiet(load_source, self.s, '(fact revenue 100 :origin "report")')
        self.assertEqual(self.s.engine._resolve_value("revenue"), 100)

    def test_resolve_fact_via_env(self):
        """Facts are also registered in env — env lookup takes priority."""
        quiet(load_source, self.s, '(fact x 42 :origin "test")')
        self.assertEqual(self.s.engine._resolve_value("x"), 42)
        self.assertIn(Symbol("x"), self.s.engine.env)

    def test_resolve_term_evaluated(self):
        quiet(load_source, self.s, '(fact a 3 :origin "test")')
        quiet(load_source, self.s, '(fact b 7 :origin "test")')
        quiet(load_source, self.s, '(defterm total (+ a b) :origin "test")')
        self.assertEqual(self.s.engine._resolve_value("total"), 10)

    def test_resolve_term_forward_declaration(self):
        quiet(load_source, self.s, '(defterm placeholder :origin "test")')
        result = self.s.engine._resolve_value("placeholder")
        self.assertEqual(result, Symbol("placeholder"))

    def test_resolve_theorem(self):
        quiet(load_source, self.s, '(fact x 5 :origin "test")')
        quiet(load_source, self.s, "(derive d1 (> x 0) :using (x))")
        result = self.s.engine._resolve_value("d1")
        self.assertEqual(result, self.s.engine.theorems["d1"].wff)

    def test_resolve_axiom(self):
        quiet(load_source, self.s, '(axiom a1 (= (+ ?a ?b) (+ ?b ?a)) :origin "test")')
        result = self.s.engine._resolve_value("a1")
        self.assertEqual(result, self.s.engine.axioms["a1"].wff)

    def test_resolve_unknown_raises(self):
        with self.assertRaises(KeyError):
            self.s.engine._resolve_value("nonexistent")

    def test_diff_with_theorem_symbol(self):
        """eval_diff must work when replace/with references a theorem."""
        quiet(
            load_source,
            self.s,
            """
            (fact x 5 :origin "test")
            (fact y 10 :origin "test")
            (defterm total (+ x y) :origin "test")
            (derive check-positive (> x 0) :using (x))
            (diff d1 :replace x :with y)
            """,
        )
        result = self.s.eval_diff("d1")
        self.assertEqual(result.value_a, 5)
        self.assertEqual(result.value_b, 10)
