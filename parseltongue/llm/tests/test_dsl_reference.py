"""Tests for dsl_reference.py — blinded and full state formatters."""

import unittest
from unittest.mock import patch

from ...core import Symbol, System
from ..dsl_reference import format_blinded_state, format_full_state


def make_system(**kwargs):
    with patch("builtins.print"):
        return System(**kwargs)


def quiet(fn, *args, **kwargs):
    with patch("builtins.print"):
        return fn(*args, **kwargs)


SAMPLE_DOC = "Apples cost $3 each."


class TestFormatBlindedState(unittest.TestCase):
    def test_shows_fact_names_and_types(self):
        s = make_system()
        quiet(s.set_fact, "price", 3.0, "test")
        quiet(s.set_fact, "count", 5, "test")

        result = format_blinded_state(s)
        self.assertIn("price", result)
        self.assertIn("float", result)
        self.assertIn("count", result)
        self.assertIn("int", result)

    def test_hides_fact_values(self):
        s = make_system()
        quiet(s.set_fact, "secret", 42, "test")

        result = format_blinded_state(s)
        self.assertNotIn("42", result)

    def test_shows_term_definitions(self):
        s = make_system()
        quiet(s.set_fact, "a", 1, "test")
        quiet(s.set_fact, "b", 2, "test")
        quiet(s.introduce_term, "total", [Symbol("+"), Symbol("a"), Symbol("b")], "test")

        result = format_blinded_state(s)
        self.assertIn("total", result)
        self.assertIn("(+ a b)", result)

    def test_shows_axiom_wffs(self):
        s = make_system()
        quiet(
            s.introduce_axiom,
            "comm",
            [Symbol("="), [Symbol("+"), Symbol("?a"), Symbol("?b")], [Symbol("+"), Symbol("?b"), Symbol("?a")]],
            "test",
        )

        result = format_blinded_state(s)
        self.assertIn("comm", result)

    def test_shows_existing_theorems(self):
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        quiet(s.derive, "pos", [Symbol(">"), Symbol("x"), 0], ["x"])

        result = format_blinded_state(s)
        self.assertIn("pos", result)
        self.assertIn("x", result)

    def test_empty_system(self):
        s = make_system()
        result = format_blinded_state(s)
        self.assertEqual(result, "")


class TestFormatFullState(unittest.TestCase):
    def test_includes_doc(self):
        s = make_system()
        result = format_full_state(s)
        # doc() output should be present
        self.assertIn("Arithmetic Operators", result)

    def test_includes_state(self):
        s = make_system()
        quiet(s.set_fact, "x", 99, "test")
        result = format_full_state(s)
        self.assertIn("x", result)
        self.assertIn("99", result)

    def test_includes_evaluated_terms(self):
        s = make_system()
        quiet(s.set_fact, "a", 3, "test")
        quiet(s.set_fact, "b", 7, "test")
        quiet(s.introduce_term, "total", [Symbol("+"), Symbol("a"), Symbol("b")], "test")

        result = format_full_state(s)
        self.assertIn("total", result)
        self.assertIn("10", result)

    def test_includes_consistency(self):
        s = make_system()
        result = format_full_state(s)
        self.assertIn("Consistency", result)

    def test_includes_diff_results(self):
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 20, "test")
        quiet(s.register_diff, "d1", "a", "b")

        result = format_full_state(s)
        self.assertIn("Diff", result)

    def test_includes_provenance(self):
        s = make_system()
        quiet(s.set_fact, "x", 5, "test origin")

        result = format_full_state(s)
        self.assertIn("Provenance", result)
        self.assertIn("x", result)


if __name__ == "__main__":
    unittest.main()
