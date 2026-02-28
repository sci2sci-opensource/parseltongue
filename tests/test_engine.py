"""Tests for Parseltongue runtime engine (engine.py)."""

import unittest
from unittest.mock import patch

from lang import Symbol, Evidence
from engine import System


# Reusable sample document text for evidence verification tests.
SAMPLE_DOC = (
    "Q3 revenue was $15M, up 15% year-over-year. "
    "Operating margin improved to 22%."
)


def make_system(**kwargs):
    """Create a System with print suppressed."""
    with patch('builtins.print'):
        return System(**kwargs)


def quiet(fn, *args, **kwargs):
    """Run a function with print suppressed."""
    with patch('builtins.print'):
        return fn(*args, **kwargs)


# ==============================================================
# Evaluation
# ==============================================================

class TestEvaluation(unittest.TestCase):

    def setUp(self):
        self.s = make_system()

    def test_add(self):
        self.assertEqual(self.s.evaluate([Symbol('+'), 2, 3]), 5)

    def test_sub(self):
        self.assertEqual(self.s.evaluate([Symbol('-'), 10, 4]), 6)

    def test_mul(self):
        self.assertEqual(self.s.evaluate([Symbol('*'), 3, 7]), 21)

    def test_div(self):
        self.assertEqual(self.s.evaluate([Symbol('/'), 10, 2]), 5.0)

    def test_mod(self):
        self.assertEqual(self.s.evaluate([Symbol('mod'), 10, 3]), 1)

    def test_gt(self):
        self.assertTrue(self.s.evaluate([Symbol('>'), 5, 3]))
        self.assertFalse(self.s.evaluate([Symbol('>'), 3, 5]))

    def test_lt(self):
        self.assertTrue(self.s.evaluate([Symbol('<'), 2, 8]))

    def test_ge(self):
        self.assertTrue(self.s.evaluate([Symbol('>='), 5, 5]))
        self.assertTrue(self.s.evaluate([Symbol('>='), 6, 5]))

    def test_le(self):
        self.assertTrue(self.s.evaluate([Symbol('<='), 5, 5]))

    def test_eq(self):
        self.assertTrue(self.s.evaluate([Symbol('='), 5, 5]))
        self.assertFalse(self.s.evaluate([Symbol('='), 5, 6]))

    def test_ne(self):
        self.assertTrue(self.s.evaluate([Symbol('!='), 5, 6]))

    def test_and(self):
        self.assertFalse(self.s.evaluate([Symbol('and'), True, False]))
        self.assertTrue(self.s.evaluate([Symbol('and'), True, True]))

    def test_or(self):
        self.assertTrue(self.s.evaluate([Symbol('or'), False, True]))
        self.assertFalse(self.s.evaluate([Symbol('or'), False, False]))

    def test_not(self):
        self.assertFalse(self.s.evaluate([Symbol('not'), True]))
        self.assertTrue(self.s.evaluate([Symbol('not'), False]))

    def test_implies(self):
        self.assertTrue(self.s.evaluate([Symbol('implies'), False, True]))
        self.assertTrue(self.s.evaluate([Symbol('implies'), True, True]))
        self.assertFalse(self.s.evaluate([Symbol('implies'), True, False]))

    def test_if_true(self):
        expr = [Symbol('if'), True, 42, 0]
        self.assertEqual(self.s.evaluate(expr), 42)

    def test_if_false(self):
        expr = [Symbol('if'), False, 42, 0]
        self.assertEqual(self.s.evaluate(expr), 0)

    def test_let(self):
        expr = [Symbol('let'), [[Symbol('x'), 10]], [Symbol('+'), Symbol('x'), 5]]
        self.assertEqual(self.s.evaluate(expr), 15)

    def test_nested(self):
        expr = [Symbol('+'), [Symbol('*'), 2, 3], [Symbol('-'), 10, 4]]
        self.assertEqual(self.s.evaluate(expr), 12)

    def test_unresolved_symbol(self):
        with self.assertRaises(NameError):
            self.s.evaluate(Symbol('unknown'))

    def test_literal_passthrough(self):
        self.assertEqual(self.s.evaluate(42), 42)
        self.assertEqual(self.s.evaluate(3.14), 3.14)
        self.assertEqual(self.s.evaluate(True), True)

    def test_local_env(self):
        result = self.s.evaluate(
            [Symbol('+'), Symbol('x'), 1],
            {Symbol('x'): 10}
        )
        self.assertEqual(result, 11)


# ==============================================================
# Facts & Overridable Flag
# ==============================================================

class TestFacts(unittest.TestCase):

    def test_set_and_retrieve_fact(self):
        s = make_system()
        quiet(s.set_fact, 'x', 42, 'test')
        self.assertEqual(s.facts['x']['value'], 42)
        self.assertEqual(s.evaluate(Symbol('x')), 42)

    def test_duplicate_fact_strict_raises(self):
        s = make_system(overridable=False)
        quiet(s.set_fact, 'x', 1, 'first')
        with self.assertRaises(ValueError):
            quiet(s.set_fact, 'x', 2, 'second')

    def test_duplicate_fact_overridable(self):
        s = make_system(overridable=True)
        quiet(s.set_fact, 'x', 1, 'first')
        quiet(s.set_fact, 'x', 2, 'second')
        self.assertEqual(s.facts['x']['value'], 2)
        self.assertEqual(s.evaluate(Symbol('x')), 2)

    def test_fact_with_evidence(self):
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        ev = Evidence(document='Doc', quotes=['Q3 revenue was $15M'])
        quiet(s.set_fact, 'rev', 15.0, ev)
        self.assertTrue(ev.verified)

    def test_fact_with_bad_evidence(self):
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        ev = Evidence(document='Doc', quotes=['This quote does not exist at all'])
        quiet(s.set_fact, 'bad', 999, ev)
        self.assertFalse(ev.verified)


# ==============================================================
# Axioms
# ==============================================================

class TestAxioms(unittest.TestCase):

    def test_introduce_axiom_string_origin(self):
        s = make_system()
        quiet(s.set_fact, 'x', 5, 'test')
        ax = quiet(s.introduce_axiom, 'a1', [Symbol('>'), Symbol('x'), 0], 'manual')
        self.assertEqual(ax.name, 'a1')
        self.assertEqual(ax.origin, 'manual')
        self.assertIn('a1', s.axioms)

    def test_introduce_axiom_evidence_origin(self):
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        quiet(s.set_fact, 'rev', 15.0, 'test')
        ev = Evidence(document='Doc', quotes=['Q3 revenue was $15M'])
        ax = quiet(s.introduce_axiom, 'a2', [Symbol('>'), Symbol('rev'), 0], ev)
        self.assertIsInstance(ax.origin, Evidence)

    def test_unknown_symbol_in_wff(self):
        s = make_system()
        with self.assertRaises(NameError):
            quiet(s.introduce_axiom, 'bad', [Symbol('>'), Symbol('unknown'), 0], 'test')


# ==============================================================
# Terms
# ==============================================================

class TestTerms(unittest.TestCase):

    def test_introduce_term(self):
        s = make_system()
        quiet(s.set_fact, 'x', 10, 'test')
        quiet(s.set_fact, 'y', 20, 'test')
        quiet(s.introduce_term, 'total', [Symbol('+'), Symbol('x'), Symbol('y')], 'test')
        self.assertIn('total', s.terms)
        result = s.evaluate(s.terms['total'].definition)
        self.assertEqual(result, 30)

    def test_term_resolves_as_symbol(self):
        """Terms auto-resolve when referenced as bare symbols."""
        s = make_system()
        quiet(s.set_fact, 'a', 3, 'test')
        quiet(s.set_fact, 'b', 4, 'test')
        quiet(s.introduce_term, 'sum_ab', [Symbol('+'), Symbol('a'), Symbol('b')], 'test')
        # Term should auto-resolve in evaluation
        result = s.evaluate(Symbol('sum_ab'))
        self.assertEqual(result, 7)


# ==============================================================
# Derivation & Fabrication Propagation
# ==============================================================

class TestDerivation(unittest.TestCase):

    def test_derive_grounded(self):
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        ev = Evidence(document='Doc', quotes=['Q3 revenue was $15M'])
        quiet(s.set_fact, 'rev', 15.0, ev)
        ax = quiet(s.derive, 'd1', [Symbol('>'), Symbol('rev'), 0], ['rev'])
        self.assertEqual(ax.origin, 'derived')
        self.assertTrue(ax.derived)
        self.assertEqual(ax.derivation, ['rev'])

    def test_derive_unverified_is_fabrication(self):
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        ev = Evidence(document='Doc', quotes=['Nonexistent quote xyz'])
        quiet(s.set_fact, 'bad', 999, ev)
        ax = quiet(s.derive, 'd2', [Symbol('>'), Symbol('bad'), 0], ['bad'])
        self.assertIn('potential fabrication', ax.origin)
        self.assertIn('bad', ax.origin)

    def test_derive_false_raises(self):
        s = make_system()
        quiet(s.set_fact, 'x', 5, 'test')
        with self.assertRaises(ValueError):
            quiet(s.derive, 'bad_d', [Symbol('<'), Symbol('x'), 0], ['x'])

    def test_fabrication_chain(self):
        """Deriving from an already-fabricated axiom propagates fabrication."""
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        ev = Evidence(document='Doc', quotes=['Nonexistent quote xyz'])
        quiet(s.set_fact, 'bad', 999, ev)
        quiet(s.derive, 'tainted', [Symbol('>'), Symbol('bad'), 0], ['bad'])
        # Now derive from tainted
        ax2 = quiet(s.derive, 'double_tainted',
                     [Symbol('>'), Symbol('bad'), 0], ['tainted'])
        self.assertIn('potential fabrication', ax2.origin)

    def test_derive_unknown_source_raises(self):
        s = make_system()
        with self.assertRaises(ValueError):
            quiet(s.derive, 'd', [Symbol('>'), 1, 0], ['nonexistent'])


# ==============================================================
# Evidence Verification & Manual Override
# ==============================================================

class TestVerification(unittest.TestCase):

    def test_document_registry(self):
        s = make_system()
        quiet(s.register_document, 'Doc', 'some text')
        self.assertIn('Doc', s.documents)
        self.assertEqual(s.documents['Doc'], 'some text')

    def test_verify_manual_evidence_origin(self):
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        ev = Evidence(document='Doc', quotes=['Nonexistent quote'])
        quiet(s.set_fact, 'x', 1, ev)
        self.assertFalse(ev.is_grounded)
        quiet(s.verify_manual, 'x')
        self.assertTrue(ev.verify_manual)
        self.assertTrue(ev.is_grounded)

    def test_verify_manual_string_origin(self):
        s = make_system()
        quiet(s.set_fact, 'x', 1, 'plain origin')
        quiet(s.verify_manual, 'x')
        origin = s.facts['x']['origin']
        self.assertIsInstance(origin, Evidence)
        self.assertTrue(origin.verify_manual)
        self.assertTrue(origin.is_grounded)

    def test_verify_manual_unknown_raises(self):
        s = make_system()
        with self.assertRaises(KeyError):
            quiet(s.verify_manual, 'nonexistent')

    def test_verify_manual_on_axiom(self):
        s = make_system()
        quiet(s.set_fact, 'x', 5, 'test')
        quiet(s.introduce_axiom, 'a1', [Symbol('>'), Symbol('x'), 0], 'string origin')
        quiet(s.verify_manual, 'a1')
        self.assertIsInstance(s.axioms['a1'].origin, Evidence)
        self.assertTrue(s.axioms['a1'].origin.is_grounded)

    def test_verify_manual_on_term(self):
        s = make_system()
        quiet(s.set_fact, 'x', 5, 'test')
        quiet(s.introduce_term, 't1', [Symbol('+'), Symbol('x'), 1], 'string origin')
        quiet(s.verify_manual, 't1')
        self.assertIsInstance(s.terms['t1'].origin, Evidence)
        self.assertTrue(s.terms['t1'].origin.is_grounded)


# ==============================================================
# Retract & Rederive
# ==============================================================

class TestRetract(unittest.TestCase):

    def test_retract_fact(self):
        s = make_system()
        quiet(s.set_fact, 'x', 1, 'test')
        quiet(s.retract, 'x')
        self.assertNotIn('x', s.facts)
        self.assertNotIn(Symbol('x'), s.env)

    def test_retract_axiom(self):
        s = make_system()
        quiet(s.set_fact, 'x', 5, 'test')
        quiet(s.introduce_axiom, 'a1', [Symbol('>'), Symbol('x'), 0], 'test')
        quiet(s.retract, 'a1')
        self.assertNotIn('a1', s.axioms)

    def test_retract_term(self):
        s = make_system()
        quiet(s.set_fact, 'x', 5, 'test')
        quiet(s.introduce_term, 't1', [Symbol('+'), Symbol('x'), 1], 'test')
        quiet(s.retract, 't1')
        self.assertNotIn('t1', s.terms)
        with self.assertRaises(NameError):
            s.evaluate(Symbol('t1'))

    def test_retract_diff(self):
        s = make_system()
        quiet(s.set_fact, 'a', 10, 'test')
        quiet(s.set_fact, 'b', 20, 'test')
        quiet(s.register_diff, 'd1', 'a', 'b')
        quiet(s.retract, 'd1')
        self.assertNotIn('d1', s.diffs)

    def test_retract_unknown_raises(self):
        s = make_system()
        with self.assertRaises(KeyError):
            quiet(s.retract, 'nonexistent')


class TestRederive(unittest.TestCase):

    def test_rederive_clears_fabrication(self):
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        ev = Evidence(document='Doc', quotes=['Nonexistent quote'])
        quiet(s.set_fact, 'x', 999, ev)
        ax = quiet(s.derive, 'd1', [Symbol('>'), Symbol('x'), 0], ['x'])
        self.assertIn('potential fabrication', ax.origin)

        # Manually verify the source
        quiet(s.verify_manual, 'x')
        quiet(s.rederive, 'd1')
        self.assertEqual(s.axioms['d1'].origin, 'derived')

    def test_rederive_non_derived_raises(self):
        s = make_system()
        quiet(s.set_fact, 'x', 5, 'test')
        quiet(s.introduce_axiom, 'a1', [Symbol('>'), Symbol('x'), 0], 'test')
        with self.assertRaises(ValueError):
            quiet(s.rederive, 'a1')

    def test_rederive_unknown_raises(self):
        s = make_system()
        with self.assertRaises(KeyError):
            quiet(s.rederive, 'nonexistent')


# ==============================================================
# Diff (Lazy)
# ==============================================================

class TestDiff(unittest.TestCase):

    def test_register_stores_params(self):
        s = make_system()
        quiet(s.set_fact, 'a', 10, 'test')
        quiet(s.set_fact, 'b', 20, 'test')
        quiet(s.register_diff, 'd1', 'a', 'b')
        self.assertIn('d1', s.diffs)
        self.assertEqual(s.diffs['d1']['replace'], 'a')
        self.assertEqual(s.diffs['d1']['with'], 'b')

    def test_eval_diff_no_divergence(self):
        s = make_system()
        quiet(s.set_fact, 'a', 10, 'test')
        quiet(s.set_fact, 'b', 10, 'test')
        quiet(s.register_diff, 'd1', 'a', 'b')
        result = s.eval_diff('d1')
        self.assertTrue(result['empty'])
        self.assertEqual(result['value_a'], 10)
        self.assertEqual(result['value_b'], 10)

    def test_eval_diff_with_divergence(self):
        s = make_system()
        quiet(s.set_fact, 'a', 10, 'test')
        quiet(s.set_fact, 'b', 20, 'test')
        quiet(s.introduce_term, 'double_a',
              [Symbol('*'), Symbol('a'), 2], 'test')
        quiet(s.register_diff, 'd1', 'a', 'b')
        result = s.eval_diff('d1')
        self.assertFalse(result['empty'])
        self.assertIn('double_a', result['divergences'])
        self.assertEqual(result['divergences']['double_a'], [20, 40])

    def test_eval_diff_laziness(self):
        """Changing a fact changes the diff result on next eval."""
        s = make_system(overridable=True)
        quiet(s.set_fact, 'a', 10, 'test')
        quiet(s.set_fact, 'b', 20, 'test')
        quiet(s.introduce_term, 'x', [Symbol('+'), Symbol('a'), 1], 'test')
        quiet(s.register_diff, 'd1', 'a', 'b')

        r1 = s.eval_diff('d1')
        self.assertFalse(r1['empty'])

        # Now make a=b so diff should be empty
        quiet(s.set_fact, 'a', 20, 'corrected')
        r2 = s.eval_diff('d1')
        self.assertTrue(r2['empty'])

    def test_eval_diff_unknown_raises(self):
        s = make_system()
        with self.assertRaises(KeyError):
            s.eval_diff('nonexistent')

    def test_eval_diff_with_term_values(self):
        """Diff where the replaced symbol is used by a term with an if-branch."""
        s = make_system()
        quiet(s.set_fact, 'growth', 15, 'test')
        quiet(s.set_fact, 'target', 10, 'test')
        quiet(s.set_fact, 'alt_growth', 5, 'test')
        quiet(s.introduce_term, 'beat',
              [Symbol('if'), [Symbol('>'), Symbol('growth'), Symbol('target')],
               True, False], 'test')
        quiet(s.register_diff, 'd1', 'growth', 'alt_growth')
        result = s.eval_diff('d1')
        self.assertFalse(result['empty'])
        self.assertIn('beat', result['divergences'])
        # growth=15 > target=10 → True; alt_growth=5 > target=10 → False
        self.assertEqual(result['divergences']['beat'], [True, False])


# ==============================================================
# Consistency
# ==============================================================

class TestConsistency(unittest.TestCase):

    def test_clean_system_consistent(self):
        s = make_system()
        report = quiet(s.consistency)
        self.assertTrue(report['consistent'])
        self.assertEqual(report['issues'], [])

    def test_unverified_evidence_issue(self):
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        ev = Evidence(document='Doc', quotes=['Nonexistent quote'])
        quiet(s.set_fact, 'x', 1, ev)
        report = quiet(s.consistency)
        self.assertFalse(report['consistent'])
        types = [i['type'] for i in report['issues']]
        self.assertIn('unverified_evidence', types)

    def test_no_evidence_issue(self):
        s = make_system()
        quiet(s.set_fact, 'x', 1, 'plain origin string')
        report = quiet(s.consistency)
        self.assertFalse(report['consistent'])
        types = [i['type'] for i in report['issues']]
        self.assertIn('no_evidence', types)

    def test_fabrication_issue(self):
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        ev = Evidence(document='Doc', quotes=['Nonexistent quote'])
        quiet(s.set_fact, 'x', 999, ev)
        quiet(s.derive, 'd1', [Symbol('>'), Symbol('x'), 0], ['x'])
        report = quiet(s.consistency)
        types = [i['type'] for i in report['issues']]
        self.assertIn('potential_fabrication', types)

    def test_diff_divergence_issue(self):
        s = make_system()
        quiet(s.set_fact, 'a', 10, 'test')
        quiet(s.set_fact, 'b', 20, 'test')
        quiet(s.introduce_term, 'ta', [Symbol('+'), Symbol('a'), 1], 'test')
        quiet(s.register_diff, 'd1', 'a', 'b')
        # Mark facts as verified to avoid no_evidence issue
        quiet(s.verify_manual, 'a')
        quiet(s.verify_manual, 'b')
        quiet(s.verify_manual, 'ta')
        report = quiet(s.consistency)
        self.assertFalse(report['consistent'])
        types = [i['type'] for i in report['issues']]
        self.assertIn('diff_divergence', types)

    def test_manually_verified_is_warning(self):
        s = make_system()
        quiet(s.set_fact, 'x', 1, 'plain')
        quiet(s.verify_manual, 'x')
        report = quiet(s.consistency)
        # Should be consistent (manually verified is not an issue)
        # but should have a warning
        warning_types = [w['type'] for w in report['warnings']]
        self.assertIn('manually_verified', warning_types)

    def test_fix_all_makes_consistent(self):
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        ev = Evidence(document='Doc', quotes=['Nonexistent quote'])
        quiet(s.set_fact, 'x', 999, ev)
        quiet(s.derive, 'd1', [Symbol('>'), Symbol('x'), 0], ['x'])

        # System inconsistent
        r1 = quiet(s.consistency)
        self.assertFalse(r1['consistent'])

        # Fix: manually verify and rederive
        quiet(s.verify_manual, 'x')
        quiet(s.rederive, 'd1')
        r2 = quiet(s.consistency)
        self.assertTrue(r2['consistent'])


# ==============================================================
# Provenance
# ==============================================================

class TestProvenance(unittest.TestCase):

    def test_fact_provenance(self):
        s = make_system()
        quiet(s.set_fact, 'x', 42, 'test origin')
        prov = s.provenance('x')
        self.assertEqual(prov['name'], 'x')
        self.assertEqual(prov['type'], 'fact')
        self.assertEqual(prov['origin'], 'test origin')

    def test_derived_provenance_chain(self):
        s = make_system()
        quiet(s.set_fact, 'x', 5, 'test')
        quiet(s.set_fact, 'y', 3, 'test')
        quiet(s.derive, 'd1', [Symbol('>'), Symbol('x'), Symbol('y')], ['x', 'y'])
        prov = s.provenance('d1')
        self.assertTrue(prov['derived'])
        self.assertEqual(len(prov['derivation_chain']), 2)

    def test_provenance_unknown_raises(self):
        s = make_system()
        with self.assertRaises(KeyError):
            s.provenance('nonexistent')

    def test_fact_provenance_with_evidence(self):
        s = make_system()
        quiet(s.register_document, 'Doc', SAMPLE_DOC)
        ev = Evidence(document='Doc', quotes=['Q3 revenue was $15M'])
        quiet(s.set_fact, 'rev', 15.0, ev)
        prov = s.provenance('rev')
        self.assertIsInstance(prov['origin'], dict)
        self.assertEqual(prov['origin']['document'], 'Doc')
        self.assertTrue(prov['origin']['grounded'])


# ==============================================================
# __repr__
# ==============================================================

class TestRepr(unittest.TestCase):

    def test_repr(self):
        s = make_system()
        r = repr(s)
        self.assertIn('System(', r)
        self.assertIn('axioms', r)
        self.assertIn('terms', r)
        self.assertIn('facts', r)
        self.assertIn('diffs', r)
        self.assertIn('docs', r)


if __name__ == '__main__':
    unittest.main()
