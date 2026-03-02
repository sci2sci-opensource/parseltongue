"""Tests for tool definitions — schema validation."""

import unittest

from ..tools import ANSWER_TOOL, DERIVE_TOOL, EXTRACT_TOOL, FACTCHECK_TOOL

ALL_TOOLS = [EXTRACT_TOOL, DERIVE_TOOL, FACTCHECK_TOOL, ANSWER_TOOL]


class TestToolSchemas(unittest.TestCase):
    def _check_tool_structure(self, tool, expected_name, expected_param):
        self.assertEqual(tool["type"], "function")
        func = tool["function"]
        self.assertEqual(func["name"], expected_name)
        self.assertIn("description", func)
        self.assertIsInstance(func["description"], str)

        params = func["parameters"]
        self.assertEqual(params["type"], "object")
        self.assertIn(expected_param, params["properties"])
        self.assertIn(expected_param, params["required"])

    def test_extract_tool(self):
        self._check_tool_structure(EXTRACT_TOOL, "extract", "dsl_output")

    def test_derive_tool(self):
        self._check_tool_structure(DERIVE_TOOL, "derive", "dsl_output")

    def test_factcheck_tool(self):
        self._check_tool_structure(FACTCHECK_TOOL, "factcheck", "dsl_output")

    def test_answer_tool(self):
        self._check_tool_structure(ANSWER_TOOL, "answer", "markdown")

    def test_four_distinct_tools(self):
        names = {t["function"]["name"] for t in ALL_TOOLS}
        self.assertEqual(len(names), 4)

    def test_descriptions_are_meaningful(self):
        for tool in ALL_TOOLS:
            desc = tool["function"]["description"]
            self.assertGreater(len(desc), 20)


if __name__ == "__main__":
    unittest.main()
