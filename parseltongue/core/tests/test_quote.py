"""Tests for the quote special form."""

import unittest

from .. import Symbol, System, load_source


class TestQuote(unittest.TestCase):
    """Test (quote ...) special form."""

    def setUp(self):
        self.s = System()

    def test_quote_symbol(self):
        result = self.s.evaluate([Symbol("quote"), Symbol("x")])
        self.assertEqual(result, Symbol("x"))

    def test_quote_prevents_evaluation(self):
        result = self.s.evaluate([Symbol("quote"), [Symbol("+"), 1, 2]])
        self.assertEqual(result, [Symbol("+"), 1, 2])

    def test_quote_in_fact(self):
        load_source(self.s, '(fact result (quote hello) :origin "test")')
        self.assertEqual(self.s.evaluate(self.s.facts["result"].wff), Symbol("hello"))
        self.assertEqual(self.s.facts["result"].wff, [Symbol('quote'), Symbol("hello")])

    def test_quote_dotted_symbol(self):
        result = self.s.evaluate([Symbol("quote"), Symbol("some.other.term")])
        self.assertEqual(result, Symbol("some.other.term"))

    def test_quote_nested_expression(self):
        result = self.s.evaluate([Symbol("quote"), [Symbol("fact"), Symbol("x"), 10, ":origin", "test"]])
        self.assertEqual(result, [Symbol("fact"), Symbol("x"), 10, ":origin", "test"])

    def test_quote_in_derivation_chain(self):
        """Quote passes raw symbol to effect, effect creates fact, derive uses it."""

        def make_fact(system, name, value):
            system.set_fact(str(name), value, "effect-generated")
            return True

        s = System(effects={"make-fact": make_fact})
        load_source(
            s,
            '''
            (make-fact (quote sensor-reading) 95)
            (fact threshold 90 :origin "spec")
            (derive sensor-ok (> sensor-reading threshold) :using (sensor-reading threshold))
        ''',
        )
        self.assertIn("sensor-ok", s.theorems)
        self.assertEqual(s.facts["sensor-reading"].wff, 95)

    def test_quoted_value_fact_in_derive_expr(self):
        """Fact with quoted value used in a derivation chain."""
        load_source(
            self.s,
            '''
            (fact mode (quote (+ 10 5)) :origin "config")
            (fact expected 15 :origin "config")
            (derive mode-check (= mode expected) :using (mode expected))
        ''',
        )
        self.assertIn("mode-check", self.s.theorems)
        self.assertTrue(self.s.evaluate(self.s.theorems["mode-check"]))

    def test_quoted_value_fact_in_derive(self):
        """Fact with quoted value used in a derivation chain."""
        load_source(
            self.s,
            '''
            (fact mode (quote production) :origin "config")
            (fact expected (quote production) :origin "config")
            (derive mode-check (= mode expected) :using (mode expected))
        ''',
        )
        self.assertIn("mode-check", self.s.theorems)
        self.assertTrue(self.s.evaluate(self.s.theorems["mode-check"]))

    def test_quote_in_effect(self):
        """Effects can receive raw expressions via quote."""
        received = []

        def capture_effect(system, *args):
            received.extend(args)
            return True

        s = System(effects={"capture": capture_effect})
        s.evaluate([Symbol("capture"), [Symbol("quote"), Symbol("raw-sym")]])
        self.assertEqual(received, [Symbol("raw-sym")])
