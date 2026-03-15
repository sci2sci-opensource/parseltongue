"""Tests for eval-time :bind on terms and theorems."""

import unittest

from ..system import System


class TestEvalBind(unittest.TestCase):
    """System-level tests for :bind at eval time."""

    def _system(self, source: str) -> System:
        s = System()
        s.interpret(source)
        return s

    def test_bind_defterm_simple(self):
        s = self._system('(defterm add-one (+ ?x 1))')
        _, result = s.interpret('(add-one :bind ((?x 41)))')
        self.assertEqual(result, 42)

    def test_bind_defterm_two_params(self):
        s = self._system('(defterm my-add (+ ?a ?b))')
        _, result = s.interpret('(my-add :bind ((?a 10) (?b 20)))')
        self.assertEqual(result, 30)

    def test_bind_theorem(self):
        s = self._system(
            """
(defterm tmpl (+ ?x ?y))
(fact a 5 :origin "test")
(fact b 3 :origin "test")
(derive thm (+ a b) :using (a b))
"""
        )
        _, result = s.interpret('(tmpl :bind ((?x 100) (?y 200)))')
        self.assertEqual(result, 300)

    def test_bind_via_axiom_rewrite(self):
        s = self._system(
            """
(defterm my-sum (+ ?a ?b))
(defterm call-sum :origin "callable")
(axiom call-sum-rule (= (call-sum ?x ?y) (my-sum :bind ((?a ?x) (?b ?y)))))
"""
        )
        _, result = s.interpret('(call-sum 7 8)')
        self.assertEqual(result, 15)

    def test_bind_preserves_var_names(self):
        """?a in bind pairs stays as Symbol after axiom substitution."""
        s = self._system(
            """
(defterm tmpl (if ?flag ?a ?b))
(defterm choose :origin "callable")
(axiom choose-rule (= (choose ?f ?x ?y) (tmpl :bind ((?flag ?f) (?a ?x) (?b ?y)))))
"""
        )
        _, r1 = s.interpret('(choose true "yes" "no")')
        self.assertEqual(r1, "yes")
        _, r2 = s.interpret('(choose false "yes" "no")')
        self.assertEqual(r2, "no")

    def test_bind_evaluates_values(self):
        """Binding values are evaluated before substitution."""
        s = self._system('(defterm tmpl (+ ?x 1))')
        _, result = s.interpret('(tmpl :bind ((?x (+ 10 20))))')
        self.assertEqual(result, 31)

    def test_bind_no_match_falls_through(self):
        """:bind on unknown head falls through to normal eval."""
        s = self._system('(fact x 42 :origin "test")')
        _, result = s.interpret('x')
        self.assertEqual(result, 42)


if __name__ == "__main__":
    unittest.main()
