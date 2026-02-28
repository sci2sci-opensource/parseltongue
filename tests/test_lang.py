"""Tests for Parseltongue language core (lang.py)."""

import unittest

from atoms import Symbol, Evidence
from lang import (
    # Re-exported from atoms (backward compat)
    tokenize, parse, to_sexp, get_keyword,
    # Constants
    IF, LET, AXIOM, DEFTERM, FACT, DERIVE, DIFF, EVIDENCE,
    SPECIAL_FORMS, DSL_KEYWORDS,
    KW_QUOTES, KW_EXPLANATION, KW_ORIGIN, KW_EVIDENCE, KW_USING,
    KW_REPLACE, KW_WITH,
    # Docs
    LANG_DOCS,
    # Functions
    parse_evidence,
)


# ==============================================================
# Symbol Constants
# ==============================================================

class TestSpecialFormConstants(unittest.TestCase):

    def test_if(self):
        self.assertEqual(IF, 'if')
        self.assertIsInstance(IF, Symbol)

    def test_let(self):
        self.assertEqual(LET, 'let')
        self.assertIsInstance(LET, Symbol)


class TestDSLKeywordConstants(unittest.TestCase):

    def test_axiom(self):
        self.assertEqual(AXIOM, 'axiom')
        self.assertIsInstance(AXIOM, Symbol)

    def test_defterm(self):
        self.assertEqual(DEFTERM, 'defterm')
        self.assertIsInstance(DEFTERM, Symbol)

    def test_fact(self):
        self.assertEqual(FACT, 'fact')
        self.assertIsInstance(FACT, Symbol)

    def test_derive(self):
        self.assertEqual(DERIVE, 'derive')
        self.assertIsInstance(DERIVE, Symbol)

    def test_diff(self):
        self.assertEqual(DIFF, 'diff')
        self.assertIsInstance(DIFF, Symbol)

    def test_evidence(self):
        self.assertEqual(EVIDENCE, 'evidence')
        self.assertIsInstance(EVIDENCE, Symbol)

    def test_dsl_keywords_tuple(self):
        self.assertEqual(DSL_KEYWORDS, (AXIOM, DEFTERM, FACT, DERIVE, DIFF, EVIDENCE))


class TestKeywordArgConstants(unittest.TestCase):

    def test_kw_quotes(self):
        self.assertEqual(KW_QUOTES, ':quotes')

    def test_kw_explanation(self):
        self.assertEqual(KW_EXPLANATION, ':explanation')

    def test_kw_origin(self):
        self.assertEqual(KW_ORIGIN, ':origin')

    def test_kw_evidence(self):
        self.assertEqual(KW_EVIDENCE, ':evidence')

    def test_kw_using(self):
        self.assertEqual(KW_USING, ':using')

    def test_kw_replace(self):
        self.assertEqual(KW_REPLACE, ':replace')

    def test_kw_with(self):
        self.assertEqual(KW_WITH, ':with')

    def test_keywords_are_strings_not_symbols(self):
        """Keyword args are plain strings, not Symbol instances."""
        for kw in (KW_QUOTES, KW_EXPLANATION, KW_ORIGIN, KW_EVIDENCE,
                   KW_USING, KW_REPLACE, KW_WITH):
            self.assertNotIsInstance(kw, Symbol)
            self.assertIsInstance(kw, str)


# ==============================================================
# Lang Docs
# ==============================================================

class TestLangDocs(unittest.TestCase):

    def test_all_special_forms_documented(self):
        for sym in SPECIAL_FORMS:
            self.assertIn(sym, LANG_DOCS, f"{sym} missing from LANG_DOCS")

    def test_all_dsl_keywords_documented(self):
        for sym in DSL_KEYWORDS:
            self.assertIn(sym, LANG_DOCS, f"{sym} missing from LANG_DOCS")

    def test_all_keyword_args_documented(self):
        for kw in (KW_QUOTES, KW_EXPLANATION, KW_ORIGIN, KW_EVIDENCE,
                   KW_USING, KW_REPLACE, KW_WITH):
            self.assertIn(kw, LANG_DOCS, f"{kw} missing from LANG_DOCS")

    def test_doc_entries_have_required_keys(self):
        for sym, doc in LANG_DOCS.items():
            self.assertIn('category', doc, f"{sym} doc missing 'category'")
            self.assertIn('description', doc, f"{sym} doc missing 'description'")
            self.assertIn('example', doc, f"{sym} doc missing 'example'")


# ==============================================================
# Backward Compatibility
# ==============================================================

class TestBackwardCompat(unittest.TestCase):
    """Ensure lang re-exports everything from atoms."""

    def test_symbol_importable(self):
        self.assertIs(Symbol, Symbol)

    def test_tokenize_importable(self):
        result = tokenize("(+ 1 2)")
        self.assertEqual(result, ['(', '+', '1', '2', ')'])

    def test_parse_importable(self):
        result = parse("(+ 1 2)")
        self.assertEqual(result, [Symbol('+'), 1, 2])

    def test_to_sexp_importable(self):
        self.assertEqual(to_sexp(42), "42")

    def test_get_keyword_importable(self):
        expr = [Symbol('fact'), Symbol('x'), 5, ':origin', 'test']
        self.assertEqual(get_keyword(expr, ':origin'), 'test')


# ==============================================================
# Parse Evidence
# ==============================================================

class TestParseEvidence(unittest.TestCase):

    def test_valid_evidence(self):
        expr = parse('(evidence "Q3 Report" :quotes ("quote one") :explanation "reason")')
        ev = parse_evidence(expr)
        self.assertEqual(ev.document, "Q3 Report")
        self.assertEqual(ev.quotes, ["quote one"])
        self.assertEqual(ev.explanation, "reason")

    def test_multiple_quotes(self):
        expr = parse('(evidence "Doc" :quotes ("q1" "q2") :explanation "x")')
        ev = parse_evidence(expr)
        self.assertEqual(ev.quotes, ["q1", "q2"])

    def test_single_quote_not_list(self):
        """Single quote passed as bare string (not in a list)."""
        expr = [Symbol('evidence'), 'Doc', ':quotes', 'single quote', ':explanation', 'x']
        ev = parse_evidence(expr)
        self.assertEqual(ev.quotes, ["single quote"])

    def test_missing_quotes(self):
        expr = parse('(evidence "Doc" :explanation "reason")')
        ev = parse_evidence(expr)
        self.assertEqual(ev.quotes, [])

    def test_invalid_not_list(self):
        with self.assertRaises(SyntaxError):
            parse_evidence("not a list")

    def test_invalid_wrong_head(self):
        expr = parse('(wrong "Doc" :quotes ("q"))')
        with self.assertRaises(SyntaxError):
            parse_evidence(expr)


if __name__ == '__main__':
    unittest.main()
