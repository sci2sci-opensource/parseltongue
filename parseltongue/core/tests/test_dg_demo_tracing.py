"""Tests for data governance demo tracing — node and edge counts.

Two test classes:
1. TestDGDemoDirectLoad — loads checker.pltg directly via LazyLoader
2. TestDGDemoBenchLoad — loads via Bench (production path, with caching)

Both run trace_engine + live_probe for the policy-check diff and report
node/edge counts. The bench path may produce different results due to
how caching and scope registration work.

Uses unittest.mock.patch to swap engines, so system.py is never edited.
"""

import logging
import os
import shutil
import tempfile
import unittest

# cd into the demo directory so .pltg relative paths resolve
_DEMO_DIR = os.path.join(
    os.path.dirname(__file__), "..", "demos", "data_governance_pltg"
)
# Same lib_paths that Bench uses — needed for correct module qualification
_CORE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _generate_vanilla():
    """Regenerate demo data with default settings (scale=1, consistent)."""
    import subprocess
    subprocess.run(
        ["python", "generate.py", "--clean", "--consistent-only", "--scale", "1"],
        cwd=_DEMO_DIR, check=True, capture_output=True,
    )


class TestDGDemoDirectLoad(unittest.TestCase):
    """Load via LazyLoader with lib_paths matching Bench."""

    @classmethod
    def setUpClass(cls):
        os.chdir(_DEMO_DIR)
        _generate_vanilla()
        logging.disable(logging.WARNING)

        from parseltongue.core.demos.data_governance_pltg.operators import (
            GOVERNANCE_EFFECTS,
        )
        from parseltongue.core.loader.lazy_loader import LazyLoader

        loader = LazyLoader(lib_paths=[_CORE_DIR])
        loader.load_main("checker.pltg", effects=GOVERNANCE_EFFECTS)
        cls.result = loader.last_result
        cls.engine = cls.result.system.engine

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)

    def test_load_counts(self):
        """Report what the direct loader produces."""
        eng = self.engine
        res = self.result
        print(f"\n  Direct load:")
        print(f"    Theorems: {len(eng.theorems)}")
        print(f"    Facts:    {len(eng.facts)}")
        print(f"    Terms:    {len(eng.terms)}")
        print(f"    Axioms:   {len(eng.axioms)}")
        print(f"    Diffs:    {len(eng.diffs)}")
        print(f"    Errors:   {len(res.errors)}")
        print(f"    Loaded:   {len(res.loaded)}")
        manifest = [f for f in eng.facts if "src.manifest" in f]
        print(f"    src.manifest facts: {len(manifest)}")
        self.assertGreater(len(eng.facts), 50)

    def test_trace_engine_edges(self):
        """trace_engine produces edges from loaded theorems."""
        from parseltongue.core.inspect.vital import trace_engine

        traced = trace_engine(self.engine)
        ed = traced.edge_dict()
        total = sum(len(v) for v in ed.values())
        print(f"\n  Direct trace: {len(traced.edges)} edges, {len(ed)} callers, {total} callees")


class TestDGDemoBenchLoad(unittest.TestCase):
    """Load via Bench — the production path with Merkle caching."""

    @classmethod
    def setUpClass(cls):
        os.chdir(_DEMO_DIR)
        logging.disable(logging.WARNING)

        from parseltongue.core.demos.data_governance_pltg.operators import (
            GOVERNANCE_EFFECTS,
        )
        from parseltongue.core.inspect.bench import Bench

        # Use a temp directory for bench cache to avoid polluting the repo
        cls._bench_dir = tempfile.mkdtemp(prefix="bench_test_")
        bench = Bench(bench_dir=cls._bench_dir)
        bench.prepare(
            os.path.join(_DEMO_DIR, "checker.pltg"),
            effects=GOVERNANCE_EFFECTS,
        )
        cls.bench = bench
        cls.result = bench.result()
        cls.engine = cls.result.system.engine

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)
        shutil.rmtree(cls._bench_dir, ignore_errors=True)

    def test_bench_load_counts(self):
        """Report what the bench loader produces."""
        eng = self.engine
        res = self.result
        print(f"\n  Bench load:")
        print(f"    Theorems: {len(eng.theorems)}")
        print(f"    Facts:    {len(eng.facts)}")
        print(f"    Terms:    {len(eng.terms)}")
        print(f"    Axioms:   {len(eng.axioms)}")
        print(f"    Diffs:    {len(eng.diffs)}")
        print(f"    Errors:   {len(res.errors)}")
        print(f"    Loaded:   {len(res.loaded)}")
        manifest = [f for f in eng.facts if "src.manifest" in f]
        print(f"    src.manifest facts: {len(manifest)}")
        self.assertGreater(len(eng.facts), 50)

    def test_bench_trace_edges(self):
        """trace_engine via bench produces edges."""
        from parseltongue.core.inspect.vital import trace_engine

        traced = trace_engine(self.engine)
        ed = traced.edge_dict()
        total = sum(len(v) for v in ed.values())
        print(f"\n  Bench trace: {len(traced.edges)} edges, {len(ed)} callers, {total} callees")
        self.assertGreater(len(traced.edges), 50)

    def test_bench_live_probe_dissect(self):
        """live_probe for both sides of policy-check diff via bench engine."""
        from parseltongue.core.inspect.vital import live_probe, trace_engine

        eng = self.engine
        if "policy-check" not in eng.diffs:
            self.skipTest("policy-check diff not loaded")

        diff = eng.diffs["policy-check"]
        left_name = diff["replace"]
        right_name = diff["with"]

        traced_l = trace_engine(eng, names=[left_name])
        left = live_probe(left_name, eng, traced_l, store="names")

        traced_r = trace_engine(eng, names=[right_name])
        right = live_probe(right_name, eng, traced_r, store="names")

        combined = set(left.graph.keys()) | set(right.graph.keys())
        left_edges = sum(len(n.inputs) for n in left.graph.values())
        right_edges = sum(len(n.inputs) for n in right.graph.values())

        print(f"\n  Bench dissect:")
        print(f"    Left nodes:  {len(left.graph)}")
        print(f"    Right nodes: {len(right.graph)}")
        print(f"    Combined:    {len(combined)}")
        print(f"    Left edges:  {left_edges}")
        print(f"    Right edges: {right_edges}")

        # Baseline from recursive engine via bench: 509 left + 2 right = 510 combined
        # Left edges: 611, right edges: 1 → 612 combined
        self.assertGreaterEqual(
            len(combined), 500,
            f"Combined dissect should have 500+ nodes (got {len(combined)})"
        )
        self.assertGreaterEqual(
            left_edges + right_edges, 600,
            f"Combined edges should be 600+ (got {left_edges + right_edges})"
        )

    def test_bench_all_theorems_evaluate(self):
        """Every theorem in the bench-loaded engine should evaluate."""
        from parseltongue.core.atoms import Symbol

        failures = []
        for tname in self.engine.theorems:
            try:
                self.engine.evaluate(Symbol(tname))
            except Exception as e:
                failures.append((tname, str(e)))

        if failures:
            msg = "\n".join(f"  {name}: {err}" for name, err in failures)
            self.fail(f"Theorems that failed to evaluate:\n{msg}")


class TestDGDemoStackEngine(unittest.TestCase):
    """Load DG demo with stack engine patched in via unittest.mock."""

    @classmethod
    def setUpClass(cls):
        from unittest.mock import patch

        os.chdir(_DEMO_DIR)
        logging.disable(logging.WARNING)

        from parseltongue.core.demos.data_governance_pltg.operators import (
            GOVERNANCE_EFFECTS,
        )
        from parseltongue.core.engines.engine_stack import Engine as StackEngine
        from parseltongue.core.loader.lazy_loader import LazyLoader

        # Patch Engine at the site where System() instantiates it
        with patch("parseltongue.core.system.Engine", StackEngine):
            loader = LazyLoader(lib_paths=[_CORE_DIR])
            loader.load_main("checker.pltg", effects=GOVERNANCE_EFFECTS)

        cls.result = loader.last_result
        cls.engine = cls.result.system.engine

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)

    def test_engine_is_stack(self):
        from parseltongue.core.engines.engine_stack import Engine as StackEngine

        self.assertIsInstance(self.engine, StackEngine)

    def test_full_load(self):
        eng = self.engine
        res = self.result
        print(f"\n  Stack engine:")
        print(f"    Theorems: {len(eng.theorems)}, Facts: {len(eng.facts)}")
        print(f"    Errors: {len(res.errors)}, Diffs: {len(eng.diffs)}")
        self.assertEqual(len(res.errors), 0, f"Errors: {[str(e) for e in res.errors.values()]}")
        self.assertEqual(len(eng.theorems), 18)
        self.assertEqual(len(eng.diffs), 1)

    def test_all_theorems_evaluate(self):
        from parseltongue.core.atoms import Symbol

        failures = []
        for tname in self.engine.theorems:
            try:
                self.engine.evaluate(Symbol(tname))
            except Exception as e:
                failures.append((tname, str(e)))
        if failures:
            self.fail("\n".join(f"  {n}: {e}" for n, e in failures))

    def test_dissect_nodes_and_edges(self):
        """Stack engine dissect should match recursive engine: 500+ nodes, 600+ edges."""
        from parseltongue.core.inspect.vital import live_probe, trace_engine

        eng = self.engine
        if "policy-check" not in eng.diffs:
            self.skipTest("policy-check diff not loaded")

        diff = eng.diffs["policy-check"]
        left_name = diff["replace"]
        right_name = diff["with"]

        traced_l = trace_engine(eng, names=[left_name])
        left = live_probe(left_name, eng, traced_l, store="names")

        traced_r = trace_engine(eng, names=[right_name])
        right = live_probe(right_name, eng, traced_r, store="names")

        combined = set(left.graph.keys()) | set(right.graph.keys())
        left_edges = sum(len(n.inputs) for n in left.graph.values())
        right_edges = sum(len(n.inputs) for n in right.graph.values())

        print(f"\n  Stack dissect:")
        print(f"    Left nodes:  {len(left.graph)}")
        print(f"    Right nodes: {len(right.graph)}")
        print(f"    Combined:    {len(combined)}")
        print(f"    Left edges:  {left_edges}")
        print(f"    Right edges: {right_edges}")

        self.assertGreaterEqual(
            len(combined), 500,
            f"Combined dissect should have 500+ nodes (got {len(combined)})"
        )
        self.assertGreaterEqual(
            left_edges + right_edges, 600,
            f"Combined edges should be 600+ (got {left_edges + right_edges})"
        )


class TestDGDemoConvergence(unittest.TestCase):
    """All load methods must converge on the same node/edge counts.

    Loads via three paths:
    1. LazyLoader + recursive engine (default)
    2. LazyLoader + stack engine (patched)
    3. Bench + recursive engine

    All must produce identical dissect results.
    """

    @classmethod
    def setUpClass(cls):
        from unittest.mock import patch

        os.chdir(_DEMO_DIR)
        _generate_vanilla()
        logging.disable(logging.WARNING)

        from parseltongue.core.demos.data_governance_pltg.operators import (
            GOVERNANCE_EFFECTS,
        )
        from parseltongue.core.engines.engine_stack import Engine as StackEngine
        from parseltongue.core.inspect.bench import Bench
        from parseltongue.core.inspect.vital import live_probe, trace_engine
        from parseltongue.core.loader.lazy_loader import LazyLoader

        def _dissect(engine):
            diff = engine.diffs["policy-check"]
            l_name, r_name = diff["replace"], diff["with"]
            tl = trace_engine(engine, names=[l_name])
            left = live_probe(l_name, engine, tl, store="names")
            tr = trace_engine(engine, names=[r_name])
            right = live_probe(r_name, engine, tr, store="names")
            combined = set(left.graph.keys()) | set(right.graph.keys())
            l_edges = sum(len(n.inputs) for n in left.graph.values())
            r_edges = sum(len(n.inputs) for n in right.graph.values())
            return {
                "left_nodes": len(left.graph),
                "right_nodes": len(right.graph),
                "combined": len(combined),
                "left_edges": l_edges,
                "right_edges": r_edges,
                "total_edges": l_edges + r_edges,
            }

        # 1. LazyLoader + recursive engine
        loader = LazyLoader(lib_paths=[_CORE_DIR])
        loader.load_main("checker.pltg", effects=GOVERNANCE_EFFECTS)
        cls.recursive = _dissect(loader.last_result.system.engine)

        # 2. LazyLoader + stack engine
        with patch("parseltongue.core.system.Engine", StackEngine):
            loader2 = LazyLoader(lib_paths=[_CORE_DIR])
            loader2.load_main("checker.pltg", effects=GOVERNANCE_EFFECTS)
        cls.stack = _dissect(loader2.last_result.system.engine)

        # 3. Bench + recursive engine
        cls._bench_dir = tempfile.mkdtemp(prefix="bench_conv_")
        bench = Bench(bench_dir=cls._bench_dir)
        bench.prepare(
            os.path.join(_DEMO_DIR, "checker.pltg"),
            effects=GOVERNANCE_EFFECTS,
        )
        cls.bench = _dissect(bench.result().system.engine)

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)
        shutil.rmtree(cls._bench_dir, ignore_errors=True)

    def test_all_methods_converge(self):
        """All three load paths must produce identical dissect counts."""
        print(f"\n  Recursive: {self.recursive}")
        print(f"  Stack:     {self.stack}")
        print(f"  Bench:     {self.bench}")

        for key in ("left_nodes", "right_nodes", "combined", "total_edges"):
            r, s, b = self.recursive[key], self.stack[key], self.bench[key]
            self.assertEqual(r, s, f"{key}: recursive ({r}) != stack ({s})")
            self.assertEqual(r, b, f"{key}: recursive ({r}) != bench ({b})")


if __name__ == "__main__":
    unittest.main()
