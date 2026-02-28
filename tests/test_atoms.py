"""Tests for Parseltongue atoms (atoms.py) — types and s-expression reader."""

import unittest

from atoms import (
    Symbol, Evidence, tokenize, atom, parse, parse_all, to_sexp,
    get_keyword,
)


class TestTokenize(unittest.TestCase):

    def test_basic_tokens(self):
        tokens = tokenize("(+ 2 3)")
        self.assertEqual(tokens, ['(', '+', '2', '3', ')'])

    def test_nested_parens(self):
        tokens = tokenize("(+ (* 2 3) 4)")
        self.assertEqual(tokens, ['(', '+', '(', '*', '2', '3', ')', '4', ')'])

    def test_string_tokens(self):
        tokens = tokenize('(fact "hello world")')
        self.assertEqual(tokens, ['(', 'fact', '"hello world"', ')'])

    def test_comments_stripped(self):
        tokens = tokenize(";; this is a comment\n(+ 1 2)")
        self.assertEqual(tokens, ['(', '+', '1', '2', ')'])

    def test_inline_comment(self):
        tokens = tokenize("(+ 1 2) ;; inline")
        self.assertEqual(tokens, ['(', '+', '1', '2', ')'])

    def test_whitespace_variants(self):
        tokens = tokenize("(+\t2\n3)")
        self.assertEqual(tokens, ['(', '+', '2', '3', ')'])

    def test_keyword_tokens(self):
        tokens = tokenize("(fact x 5 :origin \"test\")")
        self.assertEqual(tokens, ['(', 'fact', 'x', '5', ':origin', '"test"', ')'])

    def test_empty_string(self):
        tokens = tokenize("")
        self.assertEqual(tokens, [])


class TestAtom(unittest.TestCase):

    def test_integer(self):
        self.assertEqual(atom("42"), 42)
        self.assertIsInstance(atom("42"), int)

    def test_negative_integer(self):
        self.assertEqual(atom("-7"), -7)

    def test_float(self):
        self.assertAlmostEqual(atom("3.14"), 3.14)
        self.assertIsInstance(atom("3.14"), float)

    def test_bool_true(self):
        self.assertIs(atom("true"), True)

    def test_bool_false(self):
        self.assertIs(atom("false"), False)

    def test_string(self):
        result = atom('"hello"')
        self.assertEqual(result, "hello")
        self.assertNotIsInstance(result, Symbol)

    def test_keyword(self):
        result = atom(":origin")
        self.assertEqual(result, ":origin")

    def test_symbol(self):
        result = atom("foo")
        self.assertIsInstance(result, Symbol)
        self.assertEqual(result, "foo")


class TestParse(unittest.TestCase):

    def test_simple_expression(self):
        result = parse("(+ 2 3)")
        self.assertEqual(result, [Symbol('+'), 2, 3])

    def test_nested_expression(self):
        result = parse("(+ (* 2 3) (- 10 4))")
        self.assertEqual(result, [Symbol('+'), [Symbol('*'), 2, 3], [Symbol('-'), 10, 4]])

    def test_atom_only(self):
        self.assertEqual(parse("42"), 42)

    def test_symbol_only(self):
        result = parse("foo")
        self.assertIsInstance(result, Symbol)
        self.assertEqual(result, "foo")

    def test_string_literal(self):
        result = parse('"hello world"')
        self.assertEqual(result, "hello world")

    def test_bool_literal(self):
        self.assertIs(parse("true"), True)
        self.assertIs(parse("false"), False)

    def test_missing_close_paren(self):
        with self.assertRaises(SyntaxError):
            parse("(+ 1 2")

    def test_unexpected_close_paren(self):
        with self.assertRaises(SyntaxError):
            parse(")")

    def test_empty_raises(self):
        with self.assertRaises(SyntaxError):
            parse("")


class TestParseAll(unittest.TestCase):

    def test_multiple_expressions(self):
        result = parse_all("(+ 1 2) (- 3 4)")
        self.assertEqual(result, [[Symbol('+'), 1, 2], [Symbol('-'), 3, 4]])

    def test_single_expression(self):
        result = parse_all("(+ 1 2)")
        self.assertEqual(result, [[Symbol('+'), 1, 2]])

    def test_with_comments(self):
        result = parse_all(";; comment\n(+ 1 2)\n;; another\n(* 3 4)")
        self.assertEqual(result, [[Symbol('+'), 1, 2], [Symbol('*'), 3, 4]])


class TestToSexp(unittest.TestCase):

    def test_integer(self):
        self.assertEqual(to_sexp(42), "42")

    def test_float(self):
        self.assertEqual(to_sexp(3.14), "3.14")

    def test_bool(self):
        self.assertEqual(to_sexp(True), "true")
        self.assertEqual(to_sexp(False), "false")

    def test_string(self):
        self.assertEqual(to_sexp("hello"), '"hello"')

    def test_symbol(self):
        self.assertEqual(to_sexp(Symbol('foo')), "foo")

    def test_list(self):
        self.assertEqual(to_sexp([Symbol('+'), 2, 3]), "(+ 2 3)")

    def test_nested_list(self):
        expr = [Symbol('+'), [Symbol('*'), 2, 3], 4]
        self.assertEqual(to_sexp(expr), "(+ (* 2 3) 4)")

    def test_round_trip(self):
        source = "(+ (* 2 3) (- 10 4))"
        self.assertEqual(to_sexp(parse(source)), source)


class TestGetKeyword(unittest.TestCase):

    def test_found(self):
        expr = [Symbol('fact'), Symbol('x'), 5, ':origin', 'test']
        self.assertEqual(get_keyword(expr, ':origin'), 'test')

    def test_not_found(self):
        expr = [Symbol('fact'), Symbol('x'), 5]
        self.assertIsNone(get_keyword(expr, ':origin'))

    def test_default(self):
        expr = [Symbol('fact'), Symbol('x'), 5]
        self.assertEqual(get_keyword(expr, ':origin', 'fallback'), 'fallback')

    def test_keyword_at_end(self):
        """Keyword at the very end without a value returns default."""
        expr = [Symbol('fact'), Symbol('x'), ':origin']
        self.assertIsNone(get_keyword(expr, ':origin'))


class TestEvidenceDataclass(unittest.TestCase):

    def test_is_grounded_verified(self):
        ev = Evidence(document="d", quotes=[], verified=True)
        self.assertTrue(ev.is_grounded)

    def test_is_grounded_manual(self):
        ev = Evidence(document="d", quotes=[], verify_manual=True)
        self.assertTrue(ev.is_grounded)

    def test_not_grounded(self):
        ev = Evidence(document="d", quotes=[])
        self.assertFalse(ev.is_grounded)

    def test_both_grounded(self):
        ev = Evidence(document="d", quotes=[], verified=True, verify_manual=True)
        self.assertTrue(ev.is_grounded)


if __name__ == '__main__':
    unittest.main()
