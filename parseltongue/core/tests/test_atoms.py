"""Tests for Parseltongue atoms (atoms.py) — types and s-expression reader."""

import unittest

from .. import Evidence, Symbol, atom, free_vars, get_keyword, parse, parse_all, substitute, to_sexp, tokenize


class TestTokenize(unittest.TestCase):
    def test_basic_tokens(self):
        tokens = tokenize("(+ 2 3)")
        self.assertEqual(tokens, ["(", "+", "2", "3", ")"])

    def test_nested_parens(self):
        tokens = tokenize("(+ (* 2 3) 4)")
        self.assertEqual(tokens, ["(", "+", "(", "*", "2", "3", ")", "4", ")"])

    def test_string_tokens(self):
        tokens = tokenize('(fact "hello world")')
        self.assertEqual(tokens, ["(", "fact", '"hello world"', ")"])

    def test_comments_stripped(self):
        tokens = tokenize(";; this is a comment\n(+ 1 2)")
        self.assertEqual(tokens, ["(", "+", "1", "2", ")"])

    def test_inline_comment(self):
        tokens = tokenize("(+ 1 2) ;; inline")
        self.assertEqual(tokens, ["(", "+", "1", "2", ")"])

    def test_whitespace_variants(self):
        tokens = tokenize("(+\t2\n3)")
        self.assertEqual(tokens, ["(", "+", "2", "3", ")"])

    def test_keyword_tokens(self):
        tokens = tokenize('(fact x 5 :origin "test")')
        self.assertEqual(tokens, ["(", "fact", "x", "5", ":origin", '"test"', ")"])

    def test_empty_string(self):
        tokens = tokenize("")
        self.assertEqual(tokens, [])


class TestTokenizeEscapes(unittest.TestCase):
    """Escaped quotes and backslashes inside strings."""

    def test_escaped_quote_single_token(self):
        tokens = tokenize(r'"\"Licensor\" shall mean"')
        self.assertEqual(tokens, [r'"\"Licensor\" shall mean"'])

    def test_escaped_quote_in_list(self):
        tokens = tokenize(r'("\"hello\" world")')
        self.assertEqual(tokens, ["(", r'"\"hello\" world"', ")"])

    def test_escaped_backslash(self):
        tokens = tokenize(r'"path\\to\\file"')
        self.assertEqual(tokens, [r'"path\\to\\file"'])

    def test_escaped_backslash_before_quote(self):
        # \\" = escaped backslash then end-of-string
        tokens = tokenize(r'"ends with backslash\\"')
        self.assertEqual(tokens, [r'"ends with backslash\\"'])

    def test_mixed_escapes(self):
        tokens = tokenize(r'"a\"b\\c\"d"')
        self.assertEqual(tokens, [r'"a\"b\\c\"d"'])

    def test_evidence_quotes_form(self):
        source = '(:quotes ("\\\"Licensor\\\" shall mean the copyright owner"))'
        tokens = tokenize(source)
        # Should be: ( :quotes ( "..." ) )
        self.assertEqual(len(tokens), 6)
        self.assertEqual(tokens[0], "(")
        self.assertEqual(tokens[1], ":quotes")
        self.assertEqual(tokens[2], "(")
        self.assertTrue(tokens[3].startswith('"') and tokens[3].endswith('"'))
        self.assertEqual(tokens[4], ")")
        self.assertEqual(tokens[5], ")")


class TestAtomEscapes(unittest.TestCase):
    """Unescape sequences in string atoms."""

    def test_escaped_quote_unescaped(self):
        result = atom(r'"\"Licensor\""')
        self.assertEqual(result, '"Licensor"')

    def test_escaped_backslash_unescaped(self):
        result = atom(r'"path\\to"')
        self.assertEqual(result, "path\\to")

    def test_no_escapes(self):
        result = atom('"plain string"')
        self.assertEqual(result, "plain string")


class TestEscapeRoundTrip(unittest.TestCase):
    """Parse → to_sexp → parse roundtrips with escapes."""

    def test_roundtrip_escaped_quote(self):
        source = r'("\"Licensor\" shall mean")'
        parsed = parse(source)
        self.assertEqual(parsed, ['"Licensor" shall mean'])
        reparsed = parse(to_sexp(parsed))
        self.assertEqual(reparsed, parsed)

    def test_roundtrip_escaped_backslash(self):
        source = r'("path\\to\\file")'
        parsed = parse(source)
        self.assertEqual(parsed, ["path\\to\\file"])
        reparsed = parse(to_sexp(parsed))
        self.assertEqual(reparsed, parsed)

    def test_to_sexp_escapes_quotes(self):
        self.assertEqual(to_sexp('say "hello"'), r'"say \"hello\""')

    def test_to_sexp_escapes_backslashes(self):
        self.assertEqual(to_sexp("a\\b"), r'"a\\b"')


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
        self.assertEqual(result, [Symbol("+"), 2, 3])

    def test_nested_expression(self):
        result = parse("(+ (* 2 3) (- 10 4))")
        self.assertEqual(result, [Symbol("+"), [Symbol("*"), 2, 3], [Symbol("-"), 10, 4]])

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
        self.assertEqual(result, [[Symbol("+"), 1, 2], [Symbol("-"), 3, 4]])

    def test_single_expression(self):
        result = parse_all("(+ 1 2)")
        self.assertEqual(result, [[Symbol("+"), 1, 2]])

    def test_with_comments(self):
        result = parse_all(";; comment\n(+ 1 2)\n;; another\n(* 3 4)")
        self.assertEqual(result, [[Symbol("+"), 1, 2], [Symbol("*"), 3, 4]])


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
        self.assertEqual(to_sexp(Symbol("foo")), "foo")

    def test_list(self):
        self.assertEqual(to_sexp([Symbol("+"), 2, 3]), "(+ 2 3)")

    def test_nested_list(self):
        expr = [Symbol("+"), [Symbol("*"), 2, 3], 4]
        self.assertEqual(to_sexp(expr), "(+ (* 2 3) 4)")

    def test_round_trip(self):
        source = "(+ (* 2 3) (- 10 4))"
        self.assertEqual(to_sexp(parse(source)), source)


class TestGetKeyword(unittest.TestCase):
    def test_found(self):
        expr = [Symbol("fact"), Symbol("x"), 5, ":origin", "test"]
        self.assertEqual(get_keyword(expr, ":origin"), "test")

    def test_not_found(self):
        expr = [Symbol("fact"), Symbol("x"), 5]
        self.assertIsNone(get_keyword(expr, ":origin"))

    def test_default(self):
        expr = [Symbol("fact"), Symbol("x"), 5]
        self.assertEqual(get_keyword(expr, ":origin", "fallback"), "fallback")

    def test_keyword_at_end(self):
        """Keyword at the very end without a value returns default."""
        expr = [Symbol("fact"), Symbol("x"), ":origin"]
        self.assertIsNone(get_keyword(expr, ":origin"))


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


class TestFreeVars(unittest.TestCase):
    def test_simple(self):
        expr = [Symbol("="), Symbol("?n"), 0]
        self.assertEqual(free_vars(expr), {Symbol("?n")})

    def test_nested(self):
        expr = [Symbol("="), [Symbol("+"), Symbol("?a"), Symbol("?b")], [Symbol("+"), Symbol("?b"), Symbol("?a")]]
        self.assertEqual(free_vars(expr), {Symbol("?a"), Symbol("?b")})

    def test_none(self):
        expr = [Symbol("+"), 2, 3]
        self.assertEqual(free_vars(expr), set())

    def test_atom(self):
        self.assertEqual(free_vars(42), set())
        self.assertEqual(free_vars(Symbol("?x")), {Symbol("?x")})
        self.assertEqual(free_vars(Symbol("x")), set())


class TestSubstitute(unittest.TestCase):
    def test_simple(self):
        expr = [Symbol("="), Symbol("?n"), 0]
        result = substitute(expr, {Symbol("?n"): 5})
        self.assertEqual(result, [Symbol("="), 5, 0])

    def test_nested(self):
        expr = [Symbol("="), [Symbol("+"), Symbol("?a"), Symbol("?b")], [Symbol("+"), Symbol("?b"), Symbol("?a")]]
        bindings = {Symbol("?a"): 3, Symbol("?b"): 7}
        result = substitute(expr, bindings)
        self.assertEqual(result, [Symbol("="), [Symbol("+"), 3, 7], [Symbol("+"), 7, 3]])

    def test_no_match(self):
        expr = [Symbol("+"), Symbol("x"), 1]
        result = substitute(expr, {Symbol("?n"): 5})
        self.assertEqual(result, [Symbol("+"), Symbol("x"), 1])

    def test_atom_passthrough(self):
        self.assertEqual(substitute(42, {Symbol("?n"): 5}), 42)
        self.assertEqual(substitute("hello", {Symbol("?n"): 5}), "hello")


if __name__ == "__main__":
    unittest.main()
