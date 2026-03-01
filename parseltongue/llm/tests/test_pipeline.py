"""Tests for the four-pass LLM pipeline using a mock provider."""

import unittest
from unittest.mock import patch

from ...core import System
from ..pipeline import Pipeline, PipelineResult
from ..provider import LLMProvider
from ..resolve import ResolvedOutput

SAMPLE_DOC = (
    "Q3 revenue was $15M, up 15% year-over-year. "
    "The growth target for FY2024 was 10%."
)

# ── Canned tool-call responses ──────────────────────────────────

PASS1_DSL = """\
(fact revenue-q3 15.0
  :evidence (evidence "Report"
    :quotes ("Q3 revenue was $15M")
    :explanation "Q3 revenue figure"))

(fact growth 15
  :evidence (evidence "Report"
    :quotes ("up 15% year-over-year")
    :explanation "YoY growth percentage"))

(fact target 10
  :evidence (evidence "Report"
    :quotes ("The growth target for FY2024 was 10%")
    :explanation "Growth target"))
"""

PASS2_DSL = """\
(defterm beat-target (> growth target)
  :origin "Derived: growth > target")

(derive target-exceeded (> growth target)
  :using (growth target))
"""

PASS3_DSL = """\
;; Alternative growth computation for cross-check
(defterm growth-alt (- growth 0)
  :origin "Trivial identity cross-check")

(diff growth-crosscheck
  :replace growth
  :with growth-alt)
"""

PASS4_MARKDOWN = """\
The company **beat its growth target** [[fact:growth]] [[fact:target]].

Revenue was [[fact:revenue-q3]].

This is confirmed by [[theorem:target-exceeded]].
"""


class MockProvider(LLMProvider):
    """Returns canned tool-call responses for each pass."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self._call_count = 0

    def complete(self, messages, tools, **kwargs):
        resp = self._responses[self._call_count]
        self._call_count += 1
        return resp


def make_system(**kwargs):
    with patch('builtins.print'):
        return System(**kwargs)


class TestPipelineEndToEnd(unittest.TestCase):

    def test_four_pass_pipeline(self):
        system = make_system(overridable=True)
        provider = MockProvider([
            {"dsl_output": PASS1_DSL},
            {"dsl_output": PASS2_DSL},
            {"dsl_output": PASS3_DSL},
            {"markdown": PASS4_MARKDOWN},
        ])

        pipeline = Pipeline(system, provider)
        pipeline.add_document("Report", text=SAMPLE_DOC)

        with patch('builtins.print'):
            result = pipeline.run("Did we beat the growth target?")

        self.assertIsInstance(result, PipelineResult)
        self.assertIsInstance(result.output, ResolvedOutput)

        # Facts should be loaded
        self.assertIn('revenue-q3', system.facts)
        self.assertIn('growth', system.facts)
        self.assertIn('target', system.facts)
        self.assertEqual(system.facts['revenue-q3']['value'], 15.0)
        self.assertEqual(system.facts['growth']['value'], 15)
        self.assertEqual(system.facts['target']['value'], 10)

        # Term and theorem from pass 2
        self.assertIn('beat-target', system.terms)
        self.assertIn('target-exceeded', system.theorems)

        # Pass 3 fact-check artifacts
        self.assertIn('growth-alt', system.terms)
        self.assertIn('growth-crosscheck', system.diffs)

        # Pass 4 markdown preserved
        self.assertIn('beat its growth target', result.output.markdown)
        self.assertEqual(result.pass1_source, PASS1_DSL)
        self.assertEqual(result.pass2_source, PASS2_DSL)
        self.assertEqual(result.pass3_source, PASS3_DSL)
        self.assertEqual(result.pass4_raw, PASS4_MARKDOWN)

    def test_references_resolved(self):
        system = make_system(overridable=True)
        provider = MockProvider([
            {"dsl_output": PASS1_DSL},
            {"dsl_output": PASS2_DSL},
            {"dsl_output": PASS3_DSL},
            {"markdown": PASS4_MARKDOWN},
        ])

        pipeline = Pipeline(system, provider)
        pipeline.add_document("Report", text=SAMPLE_DOC)

        with patch('builtins.print'):
            result = pipeline.run("Did we beat the growth target?")

        refs = result.output.references
        ref_names = {r.name for r in refs}

        self.assertIn('growth', ref_names)
        self.assertIn('target', ref_names)
        self.assertIn('revenue-q3', ref_names)
        self.assertIn('target-exceeded', ref_names)

        # Check resolved values
        for ref in refs:
            if ref.name == 'revenue-q3':
                self.assertEqual(ref.value, 15.0)
            elif ref.name == 'growth':
                self.assertEqual(ref.value, 15)
            elif ref.name == 'target':
                self.assertEqual(ref.value, 10)

        # No errors on valid references
        for ref in refs:
            self.assertIsNone(ref.error, f"Unexpected error on {ref.name}: {ref.error}")

    def test_no_documents_raises(self):
        system = make_system()
        provider = MockProvider([])

        pipeline = Pipeline(system, provider)
        with self.assertRaises(ValueError):
            pipeline.run("test query")

    def test_provider_called_four_times(self):
        system = make_system(overridable=True)
        provider = MockProvider([
            {"dsl_output": PASS1_DSL},
            {"dsl_output": PASS2_DSL},
            {"dsl_output": PASS3_DSL},
            {"markdown": PASS4_MARKDOWN},
        ])

        pipeline = Pipeline(system, provider)
        pipeline.add_document("Report", text=SAMPLE_DOC)

        with patch('builtins.print'):
            pipeline.run("test")

        self.assertEqual(provider._call_count, 4)

    def test_str_returns_markdown(self):
        system = make_system(overridable=True)
        provider = MockProvider([
            {"dsl_output": PASS1_DSL},
            {"dsl_output": PASS2_DSL},
            {"dsl_output": PASS3_DSL},
            {"markdown": PASS4_MARKDOWN},
        ])

        pipeline = Pipeline(system, provider)
        pipeline.add_document("Report", text=SAMPLE_DOC)

        with patch('builtins.print'):
            result = pipeline.run("test")

        self.assertEqual(str(result), PASS4_MARKDOWN)


class TestPipelineAddDocument(unittest.TestCase):

    def test_add_document_text(self):
        system = make_system()
        provider = MockProvider([])
        pipeline = Pipeline(system, provider)

        pipeline.add_document("Doc", text="Some content")
        self.assertIn("Doc", system.documents)

    def test_add_document_no_args_raises(self):
        system = make_system()
        provider = MockProvider([])
        pipeline = Pipeline(system, provider)

        with self.assertRaises(ValueError):
            pipeline.add_document("Doc")


if __name__ == '__main__':
    unittest.main()
