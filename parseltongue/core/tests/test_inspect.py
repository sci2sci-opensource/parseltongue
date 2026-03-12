"""Tests for the inspect module: probe, lens, search, diagnosis, serialization."""

import unittest
from unittest.mock import patch

from parseltongue.core.inspect import inspect

from ..atoms import Evidence, Symbol
from ..inspect.diagnosis import Diagnosis, DiagnosisItem
from ..inspect.optics import Lens
from ..inspect.perspective import Perspective
from ..inspect.probe_core_to_consequence import (
    ConsumerInput,
    CoreToConsequenceStructure,
    InputType,
    Node,
    NodeKind,
    probe,
)
from ..inspect.search import Ranking, Search
from ..inspect.serialization import (
    deserialize_structure,
    serialize_structure,
)
from ..inspect.store import SearchStore
from ..quote_verifier.index import DocumentIndex
from ..system import System

SAMPLE_DOC = "Q3 revenue was $15M, up 15% year-over-year. Operating margin improved to 22%."


def _make_system(**kwargs):
    with patch("builtins.print"):
        return System(**kwargs)


def _quiet(fn, *args, **kwargs):
    with patch("builtins.print"):
        return fn(*args, **kwargs)


def _build_simple_system():
    """Build a small system with facts, axiom, term, theorem, and diff."""
    s = _make_system()
    _quiet(s.register_document, "doc", SAMPLE_DOC)
    ev = Evidence(document="doc", quotes=["Q3 revenue was $15M"])
    _quiet(s.set_fact, "revenue", 15, ev)
    _quiet(s.set_fact, "margin", 22, Evidence(document="doc", quotes=["Operating margin improved to 22%"]))
    # Axioms need ?-variables
    _quiet(s.introduce_axiom, "ax-positive", [Symbol("="), Symbol("?x"), [Symbol(">"), Symbol("?x"), 0]], ev)
    _quiet(s.introduce_term, "double-rev", [Symbol("*"), Symbol("revenue"), 2], ev)
    _quiet(s.derive, "thm-high", [Symbol(">"), Symbol("double-rev"), 10], ["double-rev"])
    _quiet(s.register_diff, "diff-rev", "revenue", "margin")
    return s


# ==============================================================
# Probe
# ==============================================================


class TestProbe(unittest.TestCase):
    def setUp(self):
        self.system = _build_simple_system()
        self.engine = self.system.engine

    def test_probe_single_term(self):
        structure = probe("thm-high", self.engine)
        self.assertIsInstance(structure, CoreToConsequenceStructure)
        self.assertIn("thm-high", structure.graph)
        self.assertGreater(len(structure.layers), 0)

    def test_probe_includes_dependencies(self):
        structure = probe("thm-high", self.engine)
        # thm-high depends on double-rev which depends on revenue
        self.assertIn("double-rev", structure.graph)
        self.assertIn("revenue", structure.graph)

    def test_probe_multiple_terms(self):
        structure = probe(["thm-high", "revenue"], self.engine)
        self.assertIn("thm-high", structure.graph)
        self.assertIn("revenue", structure.graph)

    def test_probe_fact_is_leaf(self):
        structure = probe("revenue", self.engine)
        node = structure.graph["revenue"]
        self.assertEqual(node.kind, NodeKind.FACT)
        self.assertEqual(node.inputs, [])

    def test_probe_depths_are_consistent(self):
        structure = probe("thm-high", self.engine)
        # Facts/axioms at depth 0, consumers at higher depths
        for name, depth in structure.depths.items():
            if name == "__output__":
                continue
            node = structure.graph[name]
            if node.kind == NodeKind.FACT:
                self.assertEqual(depth, 0, f"Fact {name} should be at depth 0")

    def test_probe_max_depth(self):
        structure = probe("thm-high", self.engine)
        self.assertEqual(structure.max_depth, max(structure.depths.values()))

    def test_probe_output_node(self):
        structure = probe("thm-high", self.engine)
        self.assertIn("__output__", structure.graph)

    def test_localize(self):
        structure = probe(["thm-high", "revenue"], self.engine)
        localized = structure.localize("double-rev")
        self.assertIn("double-rev", localized.graph)
        # Should include upstream (revenue) and downstream (thm-high)
        self.assertIn("revenue", localized.graph)

    def test_root_names(self):
        structure = probe("thm-high", self.engine)
        roots = structure.root_names
        self.assertIsInstance(roots, set)


# ==============================================================
# Lens
# ==============================================================


class TestLens(unittest.TestCase):
    def setUp(self):
        self.system = _build_simple_system()
        self.engine = self.system.engine
        self.structure = probe("thm-high", self.engine)

    def test_lens_creation(self):
        from ..inspect.perspectives.markdown import MarkdownPerspective

        lens = Lens(self.structure, [MarkdownPerspective()])
        self.assertIsInstance(lens, Lens)

    def test_lens_view(self):
        from ..inspect.perspectives.markdown import MarkdownPerspective

        lens = Lens(self.structure, [MarkdownPerspective()])
        result = lens.view()
        self.assertTrue(str(result))  # non-empty

    def test_lens_view_node(self):
        from ..inspect.perspectives.markdown import MarkdownPerspective

        lens = Lens(self.structure, [MarkdownPerspective()])
        result = lens.view_node("thm-high")
        self.assertIn("thm-high", str(result))

    def test_lens_view_node_not_found(self):
        from ..inspect.perspectives.markdown import MarkdownPerspective

        lens = Lens(self.structure, [MarkdownPerspective()])
        with self.assertRaises(KeyError):
            lens.view_node("nonexistent")

    def test_lens_focus(self):
        from ..inspect.perspectives.markdown import MarkdownPerspective

        lens = Lens(self.structure, [MarkdownPerspective()])
        focused = lens.focus("double-rev")
        self.assertIsInstance(focused, Lens)
        self.assertIn("double-rev", focused._names)

    def test_lens_find(self):
        from ..inspect.perspectives.markdown import MarkdownPerspective

        lens = Lens(self.structure, [MarkdownPerspective()])
        results = lens.find("thm")
        self.assertIn("thm-high", results)

    def test_lens_fuzzy(self):
        from ..inspect.perspectives.markdown import MarkdownPerspective

        lens = Lens(self.structure, [MarkdownPerspective()])
        results = lens.fuzzy("rev")
        self.assertIn("revenue", results)

    def test_lens_no_perspective_raises(self):
        lens = Lens(self.structure)
        with self.assertRaises(StopIteration):
            lens.view()

    def test_inspect_helper(self):
        lens = inspect(self.structure)
        self.assertIsInstance(lens, Lens)
        # Default perspective is MarkdownPerspective
        result = lens.view()
        self.assertTrue(str(result))

    def test_lens_view_kinds(self):
        from ..inspect.perspectives.markdown import MarkdownPerspective

        lens = Lens(self.structure, [MarkdownPerspective()])
        result = lens.view_kinds()
        self.assertTrue(str(result))

    def test_lens_view_subgraph_upstream(self):
        from ..inspect.perspectives.markdown import MarkdownPerspective

        lens = Lens(self.structure, [MarkdownPerspective()])
        result = lens.view_subgraph("thm-high", direction="upstream")
        text = str(result)
        self.assertIn("thm-high", text)

    def test_lens_view_subgraph_downstream(self):
        from ..inspect.perspectives.markdown import MarkdownPerspective

        lens = Lens(self.structure, [MarkdownPerspective()])
        result = lens.view_subgraph("revenue", direction="downstream")
        self.assertTrue(str(result))

    def test_lens_view_subgraph_both(self):
        from ..inspect.perspectives.markdown import MarkdownPerspective

        lens = Lens(self.structure, [MarkdownPerspective()])
        result = lens.view_subgraph("double-rev", direction="both")
        self.assertTrue(str(result))


# ==============================================================
# Serialization
# ==============================================================


class TestSerialization(unittest.TestCase):
    def setUp(self):
        self.system = _build_simple_system()
        self.engine = self.system.engine
        self.structure = probe("thm-high", self.engine)

    def test_roundtrip(self):
        data = serialize_structure(self.structure)
        restored = deserialize_structure(data)
        self.assertEqual(set(restored.graph.keys()), set(self.structure.graph.keys()))
        self.assertEqual(restored.max_depth, self.structure.max_depth)
        self.assertEqual(restored.depths, self.structure.depths)

    def test_roundtrip_preserves_node_kinds(self):
        data = serialize_structure(self.structure)
        restored = deserialize_structure(data)
        for name, node in self.structure.graph.items():
            self.assertEqual(restored.graph[name].kind, node.kind, f"Kind mismatch for {name}")

    def test_roundtrip_preserves_inputs(self):
        data = serialize_structure(self.structure)
        restored = deserialize_structure(data)
        for name, node in self.structure.graph.items():
            self.assertEqual(
                sorted(restored.graph[name].inputs),
                sorted(node.inputs),
                f"Inputs mismatch for {name}",
            )

    def test_roundtrip_preserves_layers(self):
        data = serialize_structure(self.structure)
        restored = deserialize_structure(data)
        self.assertEqual(len(restored.layers), len(self.structure.layers))
        for orig, rest in zip(self.structure.layers, restored.layers):
            self.assertEqual(orig.depth, rest.depth)
            self.assertEqual(len(orig.consumers), len(rest.consumers))

    def test_serialized_is_json_compatible(self):
        import json

        data = serialize_structure(self.structure)
        # Should not raise
        json.dumps(data)

    def test_empty_structure(self):
        empty = CoreToConsequenceStructure(layers=[], graph={}, depths={}, max_depth=0)
        data = serialize_structure(empty)
        restored = deserialize_structure(data)
        self.assertEqual(len(restored.graph), 0)
        self.assertEqual(len(restored.layers), 0)


# ==============================================================
# Diagnosis
# ==============================================================


class TestDiagnosis(unittest.TestCase):
    def _make_items(self):
        return [
            DiagnosisItem(name="ax-bad", category="issue", type="potential_fabrication", kind="axiom", loc="f.pltg:10"),
            DiagnosisItem(name="m1", category="warning", type="manually_verified", kind="fact", loc="f.pltg:20"),
            DiagnosisItem(name="orphan", category="dangling", type="dangling", kind="derive", loc="f.pltg:30"),
            DiagnosisItem(
                name="engine.fact-x", category="issue", type="diff_divergence", kind="diff", loc="engine.pltg:5"
            ),
            DiagnosisItem(
                name="engine.warn-y", category="warning", type="manually_verified", kind="fact", loc="engine.pltg:15"
            ),
        ]

    def test_consistent_when_no_issues(self):
        dx = Diagnosis(items=[], consistent=True)
        self.assertTrue(dx.consistent)

    def test_inconsistent_when_issues(self):
        items = self._make_items()
        dx = Diagnosis(items=items, consistent=False)
        self.assertFalse(dx.consistent)

    def test_issues_filter(self):
        dx = Diagnosis(items=self._make_items(), consistent=False)
        issues = dx.issues()
        self.assertEqual(len(issues), 2)
        self.assertTrue(all(i.category == "issue" for i in issues))

    def test_issues_filter_by_kind(self):
        dx = Diagnosis(items=self._make_items(), consistent=False)
        issues = dx.issues(kind="axiom")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].name, "ax-bad")

    def test_warnings_filter(self):
        dx = Diagnosis(items=self._make_items(), consistent=False)
        warnings = dx.warnings()
        self.assertEqual(len(warnings), 2)

    def test_danglings_filter(self):
        dx = Diagnosis(items=self._make_items(), consistent=False)
        danglings = dx.danglings()
        self.assertEqual(len(danglings), 1)
        self.assertEqual(danglings[0].name, "orphan")

    def test_focus_namespace(self):
        dx = Diagnosis(items=self._make_items(), consistent=False)
        focused = dx.focus("engine.")
        self.assertEqual(len(focused._items), 2)
        self.assertTrue(all(i.name.startswith("engine.") for i in focused._items))

    def test_find(self):
        dx = Diagnosis(items=self._make_items(), consistent=False)
        results = dx.find("engine")
        self.assertEqual(len(results), 2)

    def test_fuzzy(self):
        dx = Diagnosis(items=self._make_items(), consistent=False)
        results = dx.fuzzy("bad")
        self.assertIn("ax-bad", results)

    def test_summary_non_empty(self):
        dx = Diagnosis(items=self._make_items(), consistent=False)
        summary = dx.summary()
        self.assertIn("issue", summary)

    def test_stats(self):
        dx = Diagnosis(items=self._make_items(), consistent=False)
        stats = dx.stats()
        self.assertIn("by_category", stats)
        self.assertIn("by_type", stats)

    def test_serialization_roundtrip(self):
        dx = Diagnosis(items=self._make_items(), consistent=False)
        data = dx.to_dict()
        restored = Diagnosis.from_dict(data)
        self.assertEqual(len(restored._items), len(dx._items))
        self.assertEqual(restored.consistent, dx.consistent)
        for orig, rest in zip(dx._items, restored._items):
            self.assertEqual(orig.name, rest.name)
            self.assertEqual(orig.category, rest.category)

    def test_diagnosis_item_roundtrip(self):
        item = DiagnosisItem(name="x", category="issue", type="t", kind="fact", loc="f:1", detail="some detail")
        data = item.to_dict()
        restored = DiagnosisItem.from_dict(data)
        self.assertEqual(restored.name, "x")
        self.assertEqual(restored.category, "issue")
        self.assertEqual(restored.loc, "f:1")


# ==============================================================
# Search
# ==============================================================


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.index = DocumentIndex()
        self.index.add("doc1", "The quick brown fox jumps over the lazy dog.")
        self.index.add("doc2", "Python is a great programming language for quick prototyping.")

    def test_search_basic(self):
        search = Search(SearchStore(index=self.index))
        result = search.query("quick")
        self.assertGreater(result["total_lines"], 0)
        self.assertIn("lines", result)

    def test_search_returns_documents(self):
        search = Search(SearchStore(index=self.index))
        result = search.query("quick")
        docs = {ln["document"] for ln in result["lines"]}
        self.assertIn("doc1", docs)
        self.assertIn("doc2", docs)

    def test_search_no_match(self):
        search = Search(SearchStore(index=self.index))
        result = search.query("zzznonexistent")
        self.assertEqual(result["total_lines"], 0)
        self.assertEqual(len(result["lines"]), 0)

    def test_search_offset(self):
        search = Search(SearchStore(index=self.index))
        result_all = search.query("quick", max_lines=100)
        result_offset = search.query("quick", max_lines=100, offset=1)
        self.assertEqual(result_offset["offset"], 1)
        if result_all["total_lines"] > 1:
            self.assertEqual(len(result_offset["lines"]), len(result_all["lines"]) - 1)

    def test_search_max_lines(self):
        search = Search(SearchStore(index=self.index))
        result = search.query("quick", max_lines=1)
        self.assertLessEqual(len(result["lines"]), 1)

    def test_search_ranking_callers(self):
        search = Search(SearchStore(index=self.index))
        result = search.query("quick", rank=Ranking.CALLERS)
        self.assertIn("lines", result)

    def test_search_ranking_coverage(self):
        search = Search(SearchStore(index=self.index))
        result = search.query("quick", rank=Ranking.COVERAGE)
        self.assertIn("lines", result)

    def test_search_ranking_document(self):
        search = Search(SearchStore(index=self.index))
        result = search.query("quick", rank=Ranking.DOCUMENT)
        self.assertIn("lines", result)

    def test_search_ranking_string(self):
        search = Search(SearchStore(index=self.index))
        result = search.query("quick", rank="callers")
        self.assertIn("lines", result)

    def test_search_line_structure(self):
        search = Search(SearchStore(index=self.index))
        result = search.query("quick")
        for ln in result["lines"]:
            self.assertIn("document", ln)
            self.assertIn("line", ln)
            self.assertIn("column", ln)
            self.assertIn("context", ln)
            self.assertIn("callers", ln)
            self.assertIn("total_callers", ln)

    def test_search_with_provenance(self):
        """When quotes are registered, search returns callers."""
        self.index.register_quote("doc1", 0, 44, "fact-fox")
        search = Search(SearchStore(index=self.index))
        result = search.query("quick")
        doc1_lines = [ln for ln in result["lines"] if ln["document"] == "doc1"]
        self.assertGreater(len(doc1_lines), 0)
        # The doc1 line should have a caller
        callers = doc1_lines[0]["callers"]
        self.assertGreater(len(callers), 0)
        self.assertEqual(callers[0]["name"], "fact-fox")

    def test_search_total_callers(self):
        """total_callers counts distinct caller names."""
        self.index.register_quote("doc1", 0, 44, "fact-fox")
        self.index.register_quote("doc1", 0, 44, "ax-fox")
        search = Search(SearchStore(index=self.index))
        result = search.query("quick")
        self.assertGreaterEqual(result["total_callers"], 2)


# ==============================================================
# Perspective protocol
# ==============================================================


class TestPerspective(unittest.TestCase):
    def test_base_raises(self):
        p = Perspective()
        with self.assertRaises(NotImplementedError):
            p.render_structure(None)
        with self.assertRaises(NotImplementedError):
            p.render_node(None)
        with self.assertRaises(NotImplementedError):
            p.render_layer(None)

    def test_ascii_perspective(self):
        from ..inspect.perspectives.ascii import AsciiPerspective

        system = _build_simple_system()
        structure = probe("thm-high", system.engine)
        p = AsciiPerspective()
        result = p.render_structure(structure)
        self.assertTrue(str(result))

    def test_markdown_perspective(self):
        from ..inspect.perspectives.markdown import MarkdownPerspective

        system = _build_simple_system()
        structure = probe("thm-high", system.engine)
        p = MarkdownPerspective()
        result = p.render_structure(structure)
        self.assertTrue(str(result))


# ==============================================================
# Data structures
# ==============================================================


class TestDataStructures(unittest.TestCase):
    def test_node_kind_values(self):
        self.assertEqual(NodeKind.FACT, "fact")
        self.assertEqual(NodeKind.AXIOM, "axiom")
        self.assertEqual(NodeKind.THEOREM, "theorem")

    def test_input_type_values(self):
        self.assertEqual(InputType.DECLARE, "declare")
        self.assertEqual(InputType.USE, "use")
        self.assertEqual(InputType.PULL, "pull")

    def test_node_creation(self):
        node = Node(name="x", kind=NodeKind.FACT, value=42, inputs=[])
        self.assertEqual(node.name, "x")
        self.assertEqual(node.kind, NodeKind.FACT)

    def test_consumer_input_creation(self):
        ci = ConsumerInput(name="a", input_type=InputType.USE, source_depth=0)
        self.assertEqual(ci.name, "a")
        self.assertEqual(ci.input_type, InputType.USE)

    def test_empty_structure(self):
        s = CoreToConsequenceStructure(layers=[], graph={}, depths={}, max_depth=0)
        self.assertEqual(len(s.graph), 0)
        self.assertIsNone(s.roots)
        self.assertEqual(s.root_names, set())


if __name__ == "__main__":
    unittest.main()
