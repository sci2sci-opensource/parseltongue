"""Tests for prompt builders — verify structure and content of messages."""

import unittest
from unittest.mock import patch

from ...core import System
from ..prompts import pass1_messages, pass2_messages, pass3_messages, pass4_messages


def make_system(**kwargs):
    with patch("builtins.print"):
        return System(**kwargs)


def quiet(fn, *args, **kwargs):
    with patch("builtins.print"):
        return fn(*args, **kwargs)


class TestPass1Messages(unittest.TestCase):
    def test_returns_system_and_user(self):
        s = make_system()
        msgs = pass1_messages(s.doc(), {"Report": "Some text"}, "What happened?")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")

    def test_system_contains_dsl_reference(self):
        s = make_system()
        msgs = pass1_messages(s.doc(), {"Report": "Some text"}, "query")
        system_msg = msgs[0]["content"]
        # Should contain DSL syntax from doc()
        self.assertIn("extraction", system_msg.lower())

    def test_user_contains_documents(self):
        docs = {"Q3 Report": "Revenue was $15M", "Targets": "Growth target 10%"}
        s = make_system()
        msgs = pass1_messages(s.doc(), docs, "query")
        user_msg = msgs[1]["content"]
        self.assertIn("Q3 Report", user_msg)
        self.assertIn("Revenue was $15M", user_msg)
        self.assertIn("Targets", user_msg)
        self.assertIn("Growth target 10%", user_msg)

    def test_user_contains_query(self):
        s = make_system()
        msgs = pass1_messages(s.doc(), {"Doc": "text"}, "Did we beat target?")
        user_msg = msgs[1]["content"]
        self.assertIn("Did we beat target?", user_msg)

    def test_system_contains_evidence_format(self):
        s = make_system()
        msgs = pass1_messages(s.doc(), {"Doc": "text"}, "query")
        system_msg = msgs[0]["content"]
        self.assertIn(":evidence", system_msg)
        self.assertIn(":quotes", system_msg)
        self.assertIn(":explanation", system_msg)

    def test_system_contains_examples(self):
        s = make_system()
        msgs = pass1_messages(s.doc(), {"Doc": "text"}, "query")
        system_msg = msgs[0]["content"]
        self.assertIn("(fact", system_msg)
        self.assertIn("(defterm", system_msg)
        self.assertIn("(axiom", system_msg)


class TestPass2Messages(unittest.TestCase):
    def test_returns_system_and_user(self):
        s = make_system()
        quiet(s.set_fact, "x", 5, "test")
        msgs = pass2_messages(s.doc(), s, "query")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")

    def test_user_shows_fact_names_not_values(self):
        s = make_system()
        quiet(s.set_fact, "secret_value", 42, "test")
        msgs = pass2_messages(s.doc(), s, "query")
        user_msg = msgs[1]["content"]
        self.assertIn("secret_value", user_msg)
        # Value should be hidden — only type name shown
        self.assertIn("int", user_msg)
        self.assertNotIn("42", user_msg)

    def test_system_contains_derivation_examples(self):
        s = make_system()
        msgs = pass2_messages(s.doc(), s, "query")
        system_msg = msgs[0]["content"]
        self.assertIn("(derive", system_msg)
        self.assertIn(":using", system_msg)
        self.assertIn(":bind", system_msg)

    def test_system_contains_diff_examples(self):
        s = make_system()
        msgs = pass2_messages(s.doc(), s, "query")
        system_msg = msgs[0]["content"]
        self.assertIn("(diff", system_msg)
        self.assertIn(":replace", system_msg)
        self.assertIn(":with", system_msg)


class TestPass3Messages(unittest.TestCase):
    """Pass 3 — Fact Check (full state, cross-validation)."""

    def test_returns_system_and_user(self):
        s = make_system()
        msgs = pass3_messages(s.doc(), s, "query")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")

    def test_user_contains_full_state(self):
        s = make_system()
        quiet(s.set_fact, "revenue", 15.0, "test")
        msgs = pass3_messages(s.doc(), s, "query")
        user_msg = msgs[1]["content"]
        self.assertIn("revenue", user_msg)
        # Fact check sees values
        self.assertIn("15.0", user_msg)

    def test_system_contains_factcheck_strategy(self):
        s = make_system()
        msgs = pass3_messages(s.doc(), s, "query")
        system_msg = msgs[0]["content"]
        self.assertIn("fact-check", system_msg)
        self.assertIn("cross-validat", system_msg)
        self.assertIn("(diff", system_msg)
        self.assertIn("(fact", system_msg)
        self.assertIn("(axiom", system_msg)
        self.assertIn("(defterm", system_msg)

    def test_system_contains_dsl_reference(self):
        s = make_system()
        msgs = pass3_messages(s.doc(), s, "query")
        system_msg = msgs[0]["content"]
        # Should include the DSL reference doc
        self.assertIn("Parseltongue", system_msg)


class TestPass4Messages(unittest.TestCase):
    """Pass 4 — Inference (grounded answer)."""

    def test_returns_system_and_user(self):
        s = make_system()
        msgs = pass4_messages(s, "query")
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")

    def test_user_contains_full_state(self):
        s = make_system()
        quiet(s.set_fact, "revenue", 15.0, "test")
        msgs = pass4_messages(s, "query")
        user_msg = msgs[1]["content"]
        self.assertIn("revenue", user_msg)
        self.assertIn("15.0", user_msg)

    def test_system_contains_reference_format(self):
        s = make_system()
        msgs = pass4_messages(s, "query")
        system_msg = msgs[0]["content"]
        self.assertIn("[[fact:", system_msg)
        self.assertIn("[[term:", system_msg)
        self.assertIn("[[axiom:", system_msg)
        self.assertIn("[[theorem:", system_msg)
        self.assertIn("[[quote:", system_msg)
        self.assertIn("[[diff:", system_msg)

    def test_user_contains_consistency(self):
        s = make_system()
        quiet(s.set_fact, "x", 1, "no evidence")
        msgs = pass4_messages(s, "query")
        user_msg = msgs[1]["content"]
        self.assertIn("Consistency", user_msg)


if __name__ == "__main__":
    unittest.main()
