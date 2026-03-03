"""Tests for the reference resolver — [[type:name]] tag parsing."""

import unittest
from unittest.mock import patch

from ...core import Symbol, System
from ..resolve import TAG_RE, resolve_references


def make_system(**kwargs):
    with patch("builtins.print"):
        return System(**kwargs)


def quiet(fn, *args, **kwargs):
    with patch("builtins.print"):
        return fn(*args, **kwargs)


SAMPLE_DOC = "Q3 revenue was $15M and margin was 22%."


class TestTagRegex(unittest.TestCase):
    def test_matches_valid_tags(self):
        text = "See [[fact:revenue]] and [[theorem:target-exceeded]]."
        matches = TAG_RE.findall(text)
        self.assertEqual(matches, [("fact", "revenue"), ("theorem", "target-exceeded")])

    def test_matches_all_types(self):
        text = "[[fact:a]] [[term:b]] [[axiom:c]] [[theorem:d]] [[quote:e]] [[diff:f]]"
        types = [m[0] for m in TAG_RE.findall(text)]
        self.assertEqual(types, ["fact", "term", "axiom", "theorem", "quote", "diff"])

    def test_no_match_on_malformed(self):
        self.assertEqual(TAG_RE.findall("no tags here"), [])
        self.assertEqual(TAG_RE.findall("[fact:x]"), [])  # single brackets
        self.assertEqual(TAG_RE.findall("[[]]"), [])

    def test_hyphenated_names(self):
        matches = TAG_RE.findall("[[fact:revenue-q3-growth]]")
        self.assertEqual(matches, [("fact", "revenue-q3-growth")])


class TestResolveFact(unittest.TestCase):
    def test_resolve_known_fact(self):
        s = make_system()
        quiet(s.set_fact, "revenue", 15.0, "test")

        result = resolve_references("Revenue: [[fact:revenue]]", s)
        self.assertEqual(len(result.references), 1)
        ref = result.references[0]
        self.assertEqual(ref.type, "fact")
        self.assertEqual(ref.name, "revenue")
        self.assertEqual(ref.value, 15.0)
        self.assertIsNone(ref.error)

    def test_resolve_unknown_fact(self):
        s = make_system()

        result = resolve_references("[[fact:nonexistent]]", s)
        ref = result.references[0]
        self.assertIsNotNone(ref.error)
        self.assertIn("unknown fact", ref.error)


class TestResolveTerm(unittest.TestCase):
    def test_resolve_computed_term(self):
        s = make_system()
        quiet(s.set_fact, "a", 3, "test")
        quiet(s.set_fact, "b", 7, "test")
        quiet(s.introduce_term, "total", [Symbol("+"), Symbol("a"), Symbol("b")], "test")

        result = resolve_references("Total: [[term:total]]", s)
        ref = result.references[0]
        self.assertEqual(ref.value, 10)
        self.assertIsNone(ref.error)

    def test_resolve_forward_declaration(self):
        s = make_system()
        quiet(s.introduce_term, "zero", None, "test")

        result = resolve_references("[[term:zero]]", s)
        ref = result.references[0]
        self.assertEqual(ref.value, "(forward declaration)")

    def test_resolve_unknown_term(self):
        s = make_system()

        result = resolve_references("[[term:nope]]", s)
        ref = result.references[0]
        self.assertIn("unknown term", ref.error)


class TestResolveAxiom(unittest.TestCase):
    def test_resolve_known_axiom(self):
        s = make_system()
        quiet(
            s.introduce_axiom,
            "add-comm",
            [Symbol("="), [Symbol("+"), Symbol("?a"), Symbol("?b")], [Symbol("+"), Symbol("?b"), Symbol("?a")]],
            "test",
        )

        result = resolve_references("[[axiom:add-comm]]", s)
        ref = result.references[0]
        self.assertIsNone(ref.error)
        self.assertIn("=", ref.value)

    def test_resolve_unknown_axiom(self):
        s = make_system()

        result = resolve_references("[[axiom:nope]]", s)
        ref = result.references[0]
        self.assertIn("unknown axiom", ref.error)


class TestResolveTheorem(unittest.TestCase):
    def test_resolve_known_theorem(self):
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        quiet(s.derive, "positive", [Symbol(">"), Symbol("x"), 0], ["x"])

        result = resolve_references("[[theorem:positive]]", s)
        ref = result.references[0]
        self.assertIsNone(ref.error)
        self.assertIn(">", ref.value)

    def test_resolve_unknown_theorem(self):
        s = make_system()

        result = resolve_references("[[theorem:nope]]", s)
        ref = result.references[0]
        self.assertIn("unknown theorem", ref.error)


class TestResolveQuote(unittest.TestCase):
    def test_quote_pulls_provenance(self):
        s = make_system()
        quiet(s.set_fact, "x", 42, "test origin")

        result = resolve_references("[[quote:x]]", s)
        ref = result.references[0]
        self.assertIsNotNone(ref.provenance)
        self.assertEqual(ref.provenance["name"], "x")


class TestResolveDiff(unittest.TestCase):
    def test_resolve_known_diff(self):
        s = make_system()
        quiet(s.set_fact, "a", 10, "test")
        quiet(s.set_fact, "b", 10, "test")
        quiet(s.register_diff, "d1", "a", "b")

        result = resolve_references("[[diff:d1]]", s)
        ref = result.references[0]
        self.assertIsNone(ref.error)
        self.assertTrue(ref.value.empty)

    def test_resolve_unknown_diff(self):
        s = make_system()

        result = resolve_references("[[diff:nope]]", s)
        ref = result.references[0]
        self.assertIn("unknown diff", ref.error)


class TestResolveOutput(unittest.TestCase):
    def test_dedup(self):
        """Duplicate tags should only produce one reference."""
        s = make_system()
        quiet(s.set_fact, "x", 1, "test")

        result = resolve_references("[[fact:x]] and again [[fact:x]]", s)
        self.assertEqual(len(result.references), 1)

    def test_unknown_type(self):
        s = make_system()

        result = resolve_references("[[banana:x]]", s)
        ref = result.references[0]
        self.assertIn("unknown reference type", ref.error)

    def test_consistency_included(self):
        s = make_system()

        result = resolve_references("No tags", s)
        self.assertIsInstance(result.consistency, dict)

    def test_markdown_preserved(self):
        s = make_system()
        md = "# Hello\n\nNo tags here."

        result = resolve_references(md, s)
        self.assertEqual(result.markdown, md)

    def test_str_returns_markdown(self):
        s = make_system()
        md = "output text"
        result = resolve_references(md, s)
        self.assertEqual(str(result), md)


if __name__ == "__main__":
    unittest.main()
