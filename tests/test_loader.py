"""Tests for Parseltongue DSL loader (load_source / _execute_directive)."""

import unittest
from unittest.mock import patch

from lang import Evidence
from engine import System, load_source


SAMPLE_DOC = "Revenue growth target for FY2024: 10%. Q3 revenue was $15M."


def make_system(**kwargs):
    with patch('builtins.print'):
        return System(**kwargs)


def quiet(fn, *args, **kwargs):
    with patch('builtins.print'):
        return fn(*args, **kwargs)


class TestFactDirective(unittest.TestCase):

    def test_fact_with_origin(self):
        s = make_system()
        quiet(load_source, s, '(fact revenue 15 :origin "Q3 report")')
        self.assertIn('revenue', s.facts)
        self.assertEqual(s.facts['revenue']['value'], 15)
        self.assertEqual(s.facts['revenue']['origin'], 'Q3 report')

    def test_fact_with_evidence(self):
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        quiet(load_source, s, """
            (fact rev 15
              :evidence (evidence "Doc"
                :quotes ("Q3 revenue was $15M")
                :explanation "revenue figure"))
        """)
        self.assertIn('rev', s.facts)
        origin = s.facts['rev']['origin']
        self.assertIsInstance(origin, Evidence)
        self.assertEqual(origin.document, 'Doc')

    def test_fact_float_value(self):
        s = make_system()
        quiet(load_source, s, '(fact rate 0.15 :origin "test")')
        self.assertAlmostEqual(s.facts['rate']['value'], 0.15)


class TestAxiomDirective(unittest.TestCase):

    def test_axiom(self):
        s = make_system()
        quiet(s.set_fact, 'x', 5, 'test')
        quiet(load_source, s, '(axiom a1 (> x 0) :origin "test")')
        self.assertIn('a1', s.axioms)

    def test_axiom_with_evidence(self):
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        quiet(s.set_fact, 'x', 5, 'test')
        quiet(load_source, s, """
            (axiom a2 (> x 0)
              :evidence (evidence "Doc"
                :quotes ("Revenue growth target for FY2024: 10%")
                :explanation "test"))
        """)
        self.assertIsInstance(s.axioms['a2'].origin, Evidence)


class TestDeftermDirective(unittest.TestCase):

    def test_defterm(self):
        s = make_system()
        quiet(s.set_fact, 'a', 10, 'test')
        quiet(s.set_fact, 'b', 20, 'test')
        quiet(load_source, s, '(defterm total (+ a b) :origin "test")')
        self.assertIn('total', s.terms)
        result = s.evaluate(s.terms['total'].definition)
        self.assertEqual(result, 30)

    def test_defterm_with_evidence(self):
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        quiet(s.set_fact, 'a', 10, 'test')
        quiet(load_source, s, """
            (defterm double_a (* a 2)
              :evidence (evidence "Doc"
                :quotes ("Revenue growth target for FY2024: 10%")
                :explanation "test"))
        """)
        self.assertIsInstance(s.terms['double_a'].origin, Evidence)


class TestDeriveDirective(unittest.TestCase):

    def test_derive(self):
        s = make_system()
        quiet(s.set_fact, 'x', 5, 'test')
        quiet(s.verify_manual, 'x')
        quiet(load_source, s, '(derive d1 (> x 0) :using (x))')
        self.assertIn('d1', s.axioms)
        self.assertTrue(s.axioms['d1'].derived)
        self.assertEqual(s.axioms['d1'].derivation, ['x'])


class TestDiffDirective(unittest.TestCase):

    def test_diff(self):
        s = make_system()
        quiet(s.set_fact, 'a', 10, 'test')
        quiet(s.set_fact, 'b', 20, 'test')
        quiet(load_source, s, '(diff d1 :replace a :with b)')
        self.assertIn('d1', s.diffs)
        self.assertEqual(s.diffs['d1']['replace'], 'a')
        self.assertEqual(s.diffs['d1']['with'], 'b')


class TestMultipleDirectives(unittest.TestCase):

    def test_multiple_in_one_source(self):
        s = make_system()
        quiet(load_source, s, """
            (fact x 10 :origin "test")
            (fact y 20 :origin "test")
        """)
        self.assertIn('x', s.facts)
        self.assertIn('y', s.facts)
        self.assertEqual(s.facts['x']['value'], 10)
        self.assertEqual(s.facts['y']['value'], 20)

    def test_comments_ignored(self):
        s = make_system()
        quiet(load_source, s, """
            ;; This is a comment
            (fact x 10 :origin "test")
            ;; Another comment
            (fact y 20 :origin "test")
        """)
        self.assertIn('x', s.facts)
        self.assertIn('y', s.facts)

    def test_mixed_directives(self):
        s = make_system()
        quiet(load_source, s, """
            (fact a 5 :origin "test")
            (fact b 10 :origin "test")
            (defterm sum_ab (+ a b) :origin "test")
            (diff d1 :replace a :with b)
        """)
        self.assertIn('a', s.facts)
        self.assertIn('sum_ab', s.terms)
        self.assertIn('d1', s.diffs)


class TestDefaultOrigin(unittest.TestCase):

    def test_fact_no_origin_defaults_to_unknown(self):
        s = make_system()
        quiet(load_source, s, '(fact x 10)')
        self.assertEqual(s.facts['x']['origin'], 'unknown')


if __name__ == '__main__':
    unittest.main()
