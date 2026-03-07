"""Tests for Parseltongue AST (ast.py) — directive parsing and dependency graph."""

import os
import shutil
import tempfile
import unittest

from ..ast import DirectiveNode, extract_symbols, parse_directive, resolve_graph
from ..atoms import Symbol


class _TmpDirMixin:
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path


class TestExtractSymbols(unittest.TestCase):

    def test_single_symbol(self):
        out = set()
        extract_symbols(Symbol("foo"), out)
        self.assertEqual(out, {"foo"})

    def test_skips_variables(self):
        out = set()
        extract_symbols(Symbol("?x"), out)
        self.assertEqual(out, set())

    def test_skips_keywords(self):
        out = set()
        extract_symbols(Symbol(":using"), out)
        self.assertEqual(out, set())

    def test_nested_list(self):
        out = set()
        extract_symbols([Symbol("and"), [Symbol(">"), Symbol("a"), Symbol("b")], Symbol("c")], out)
        self.assertEqual(out, {"and", ">", "a", "b", "c"})

    def test_mixed_types(self):
        out = set()
        extract_symbols([Symbol("foo"), 42, "hello", Symbol("bar")], out)
        self.assertEqual(out, {"foo", "bar"})

    def test_empty(self):
        out = set()
        extract_symbols([], out)
        self.assertEqual(out, set())


class TestParseDirective(unittest.TestCase):

    def test_fact(self):
        expr = [Symbol("fact"), Symbol("x"), 5, ":origin", "test"]
        node = parse_directive(expr)
        self.assertEqual(node.name, "x")
        self.assertEqual(node.kind, "fact")
        self.assertEqual(node.dep_names, set())

    def test_fact_with_expression_value(self):
        expr = [Symbol("fact"), Symbol("x"), [Symbol("+"), Symbol("a"), Symbol("b")], ":origin", "test"]
        node = parse_directive(expr)
        self.assertEqual(node.name, "x")
        self.assertEqual(node.dep_names, {"+", "a", "b"})

    def test_axiom(self):
        expr = [
            Symbol("axiom"),
            Symbol("rule"),
            [Symbol("="), [Symbol("+"), Symbol("?n"), Symbol("zero")], Symbol("?n")],
        ]
        node = parse_directive(expr)
        self.assertEqual(node.name, "rule")
        self.assertEqual(node.kind, "axiom")
        self.assertIn("zero", node.dep_names)
        self.assertNotIn("?n", node.dep_names)

    def test_defterm_computed(self):
        expr = [Symbol("defterm"), Symbol("total"), [Symbol("+"), Symbol("a"), Symbol("b")], ":origin", "def"]
        node = parse_directive(expr)
        self.assertEqual(node.name, "total")
        self.assertEqual(node.kind, "defterm")
        self.assertEqual(node.dep_names, {"+", "a", "b"})

    def test_defterm_forward_decl(self):
        expr = [Symbol("defterm"), Symbol("zero"), ":origin", "primitive"]
        node = parse_directive(expr)
        self.assertEqual(node.name, "zero")
        self.assertEqual(node.dep_names, set())

    def test_defterm_alias(self):
        expr = [Symbol("defterm"), Symbol("local-zero"), Symbol("mod.zero"), ":origin", "import"]
        node = parse_directive(expr)
        self.assertEqual(node.name, "local-zero")
        self.assertIn("mod.zero", node.dep_names)

    def test_derive_with_using(self):
        expr = [Symbol("derive"), Symbol("thm"), [Symbol(">"), Symbol("x"), 0], ":using", [Symbol("x")]]
        node = parse_directive(expr)
        self.assertEqual(node.name, "thm")
        self.assertEqual(node.kind, "derive")
        self.assertIn("x", node.dep_names)

    def test_derive_body_deps(self):
        expr = [
            Symbol("derive"),
            Symbol("thm"),
            [Symbol("and"), Symbol("a"), Symbol("b")],
            ":using",
            [Symbol("a"), Symbol("b")],
        ]
        node = parse_directive(expr)
        self.assertIn("a", node.dep_names)
        self.assertIn("b", node.dep_names)
        self.assertIn("and", node.dep_names)

    def test_derive_with_bind(self):
        expr = [
            Symbol("derive"),
            Symbol("thm"),
            Symbol("axiom-name"),
            ":bind",
            [[Symbol("?n"), Symbol("val")]],
            ":using",
            [Symbol("axiom-name"), Symbol("val")],
        ]
        node = parse_directive(expr)
        self.assertIn("axiom-name", node.dep_names)
        self.assertIn("val", node.dep_names)

    def test_diff(self):
        expr = [Symbol("diff"), Symbol("check"), ":replace", Symbol("old"), ":with", Symbol("new")]
        node = parse_directive(expr)
        self.assertEqual(node.name, "check")
        self.assertEqual(node.kind, "diff")
        self.assertEqual(node.dep_names, {"old", "new"})

    def test_effect(self):
        expr = [Symbol("print"), "hello"]
        node = parse_directive(expr)
        self.assertIsNone(node.name)
        self.assertEqual(node.kind, "effect")

    def test_source_order(self):
        node = parse_directive([Symbol("fact"), Symbol("x"), 1], order=7)
        self.assertEqual(node.source_order, 7)


class TestResolveGraph(unittest.TestCase):

    def test_links_children_and_dependents(self):
        n1 = DirectiveNode(name="a", expr=[], dep_names=set(), kind="fact")
        n2 = DirectiveNode(name="b", expr=[], dep_names={"a"}, kind="derive")
        resolve_graph([n1, n2])
        self.assertIn(n1, n2.children)
        self.assertIn(n2, n1.dependents)

    def test_external_deps_ignored(self):
        n1 = DirectiveNode(name="x", expr=[], dep_names={"external-thing"}, kind="derive")
        index = resolve_graph([n1])
        self.assertEqual(n1.children, [])

    def test_chain(self):
        n1 = DirectiveNode(name="a", expr=[], dep_names=set(), kind="fact")
        n2 = DirectiveNode(name="b", expr=[], dep_names={"a"}, kind="derive")
        n3 = DirectiveNode(name="c", expr=[], dep_names={"b"}, kind="diff")
        resolve_graph([n1, n2, n3])
        self.assertIn(n1, n2.children)
        self.assertIn(n2, n3.children)
        self.assertIn(n3, n2.dependents)

    def test_diamond(self):
        base = DirectiveNode(name="base", expr=[], dep_names=set(), kind="fact")
        left = DirectiveNode(name="left", expr=[], dep_names={"base"}, kind="derive")
        right = DirectiveNode(name="right", expr=[], dep_names={"base"}, kind="derive")
        top = DirectiveNode(name="top", expr=[], dep_names={"left", "right"}, kind="diff")
        resolve_graph([base, left, right, top])
        self.assertEqual(len(base.dependents), 2)
        self.assertEqual(len(top.children), 2)

    def test_walk_dependents(self):
        n1 = DirectiveNode(name="root", expr=[], dep_names=set(), kind="fact")
        n2 = DirectiveNode(name="mid", expr=[], dep_names={"root"}, kind="derive")
        n3 = DirectiveNode(name="leaf", expr=[], dep_names={"mid"}, kind="diff")
        resolve_graph([n1, n2, n3])
        deps = n1.walk_dependents()
        names = {n.name for n in deps}
        self.assertEqual(names, {"mid", "leaf"})

    def test_returns_index(self):
        n1 = DirectiveNode(name="a", expr=[], dep_names=set(), kind="fact")
        n2 = DirectiveNode(name=None, expr=[], dep_names=set(), kind="effect")
        index = resolve_graph([n1, n2])
        self.assertIn("a", index)
        self.assertNotIn(None, index)


class TestAstFromPltg(_TmpDirMixin, unittest.TestCase):
    """Parse .pltg files through the real tokenizer and verify AST structure."""

    def _parse_nodes(self, source):
        from ..atoms import read_tokens, tokenize

        tokens = tokenize(source)
        nodes = []
        order = 0
        while tokens:
            expr = read_tokens(tokens)
            nodes.append(parse_directive(expr, order))
            order += 1
        return nodes

    def test_fact_chain(self):
        nodes = self._parse_nodes(
            '''
            (fact a 1 :origin "test")
            (fact b (+ a 1) :origin "test")
            (derive c (> b 0) :using (b))
        '''
        )
        self.assertEqual(len(nodes), 3)
        self.assertEqual(nodes[0].name, "a")
        self.assertIn("a", nodes[1].dep_names)
        self.assertIn("b", nodes[2].dep_names)

    def test_graph_from_pltg(self):
        nodes = self._parse_nodes(
            '''
            (fact x 1 :origin "test")
            (fact y 2 :origin "test")
            (derive z (+ x y) :using (x y))
            (diff check :replace z :with x)
        '''
        )
        index = resolve_graph(nodes)
        self.assertIn("x", index["z"].dep_names)
        self.assertIn("y", index["z"].dep_names)
        self.assertIn(index["x"], index["z"].children)
        self.assertIn(index["y"], index["z"].children)
        self.assertIn(index["z"], index["check"].children)

    def test_count_exists_deps(self):
        nodes = self._parse_nodes(
            '''
            (fact a true :origin "test")
            (fact b true :origin "test")
            (derive count (count-exists a b) :using (count-exists a b))
        '''
        )
        count_node = nodes[2]
        self.assertIn("a", count_node.dep_names)
        self.assertIn("b", count_node.dep_names)
        self.assertIn("count-exists", count_node.dep_names)

    def test_effects_have_no_name(self):
        nodes = self._parse_nodes(
            '''
            (print "hello")
            (fact x 1 :origin "test")
            (print "bye")
        '''
        )
        self.assertIsNone(nodes[0].name)
        self.assertEqual(nodes[1].name, "x")
        self.assertIsNone(nodes[2].name)

    def test_diff_deps_on_both_sides(self):
        nodes = self._parse_nodes(
            '''
            (fact a 1 :origin "test")
            (fact b 2 :origin "test")
            (diff check :replace a :with b)
        '''
        )
        diff_node = nodes[2]
        self.assertEqual(diff_node.dep_names, {"a", "b"})
