"""Architectural invariants — stated in the language, verified on the real tree.

validation/architecture.pltg declares its own corpus (load-documents) and
its claims; loading it through the ordinary loader grounds them, so the
invariant rides standard consistency wherever the module is imported.
"""

import os
import shutil
import unittest

from ..engine import IssueType
from ..loader import LazyLoader

ARCH_PLTG = os.path.join(os.path.dirname(__file__), "..", "validation", "architecture.pltg")


class TestArchitectureClaims(unittest.TestCase):
    def test_core_independent_of_bench_verifies(self):
        system = LazyLoader().load_main(ARCH_PLTG, strict=True)
        for name in ("no-relative-bench-import", "no-absolute-bench-import", "no-dynamic-bench-import"):
            origin = system.engine.facts[name].origin
            self.assertTrue(origin.is_grounded, (name, origin.verification))
            record = origin.verification[0]
            self.assertGreater(record["checked_files"], 50)  # quantifies over the real corpus
            self.assertNotIn(  # the sentence's own :except carved these, not the corpus assembly
                "parseltongue/core/inspect/bench.py", record["content_hashes"]
            )
        composite = system.engine.theorems["core-independent-of-bench"]
        self.assertNotIn("potential fabrication", str(composite.origin))
        report = system.engine.consistency()
        self.assertTrue(report.consistent, [str(i) for i in report.issues])

    def test_boundary_does_not_match_inspector(self):
        """`from .inspector import x` is not a bench import — \\b holds the line."""
        system = LazyLoader().load_main(ARCH_PLTG, strict=True)
        system.engine.register_document("parseltongue/core/uses_inspector.py", "from .inspector import gadget\n")
        self.assertTrue(system.engine.facts["no-relative-bench-import"].origin.is_grounded)


TEST_DIR = "/tmp/architecture-claims-negative"

_NEGATIVE_PLTG = """
(load-documents "corpus" "../src/**/*.py")

(fact no-bench-imports true
  :evidence (evidence "corpus"
             :absent (re "from \\\\.inspect")
             :except ("tests/")))
"""


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


class TestNegativeControl(unittest.TestCase):
    """The invariant refutes — it does not vacuously pass."""

    def setUp(self):
        shutil.rmtree(TEST_DIR, ignore_errors=True)
        _write(os.path.join(TEST_DIR, "src/ok.py"), "x = 1\n")
        _write(os.path.join(TEST_DIR, "src/tests/exempt.py"), "from .inspect import fine_here\n")
        _write(os.path.join(TEST_DIR, "validation/claims.pltg"), _NEGATIVE_PLTG)

    def tearDown(self):
        shutil.rmtree(TEST_DIR, ignore_errors=True)

    def _load(self):
        return LazyLoader().load_main(os.path.join(TEST_DIR, "validation/claims.pltg"), strict=True)

    def test_clean_tree_grounds_and_except_exempts(self):
        system = self._load()
        self.assertTrue(system.engine.facts["no-bench-imports"].origin.is_grounded)

    def test_breach_is_refuted_with_counter_example(self):
        _write(os.path.join(TEST_DIR, "src/rogue.py"), "from .inspect import bench  # breach\n")
        system = self._load()
        report = system.engine.consistency()
        self.assertFalse(report.consistent)
        by_type = {i.type: i.items for i in report.issues}
        name, examples = by_type[IssueType.ABSENCE_VIOLATED][0]
        self.assertEqual(name, "no-bench-imports")
        self.assertEqual(examples[0][0], "corpus/rogue.py")
        self.assertIn("from .inspect import", examples[0][2])


if __name__ == "__main__":
    unittest.main()
