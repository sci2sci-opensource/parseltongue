"""Test that execute_pgmd patches import aliases before re-interpret.

Regression test: when a pgmd notebook uses (import (quote std.counting c)),
re-interpret (step 3) must resolve c.count-exists → std.counting.count-exists
so axiom rewriting works. Without patching, derives using aliased axioms
stay unreduced (returning lists instead of values), breaking downstream
axiom binds like (< (strict ?n) 30).
"""

import os
import shutil
import tempfile
import unittest

from ..inspect.notebooks.executor import execute_pgmd


class TestExecutorAliasPatching(unittest.TestCase):
    """Import alias resolution survives re-interpret in execute_pgmd."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="executor_alias_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, content):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_aliased_count_exists_reduces_in_reinterpret(self):
        """c.count-exists via aliased import must reduce during re-interpret."""
        pgmd = self._write(
            "test.pg.md",
            """\
# Test

```scheme
;; pltg Block1
(import (quote std.counting c))
(fact a true :origin "t")
(fact b true :origin "t")
(fact d true :origin "t")
(derive count-a (c.count-exists a b) :using (c.count-exists a b))
(derive count-b (c.count-exists d) :using (c.count-exists d))
```

```scheme
;; pltg Block2
(derive total (c.sum-values count-a count-b) :using (c.sum-values count-a count-b))
(axiom check-axiom (< (strict ?n) 100) :origin "test")
(verify-manual (quote check-axiom) "V")
(derive check check-axiom :bind ((?n total)) :using (total check-axiom))
```
""",
        )
        result = execute_pgmd(pgmd)

        # No block errors
        for num, bo in result.block_outputs.items():
            self.assertIsNone(bo.error, f"Block {num} error: {bo.error}")

        # Bench values are correct
        eng = result.bench.result(str(result.comp_path)).system.engine
        self.assertEqual(eng.evaluate(eng.theorems["count-a"].wff), 2)
        self.assertEqual(eng.evaluate(eng.theorems["count-b"].wff), 1)
        self.assertEqual(eng.evaluate(eng.theorems["total"].wff), 3)
        self.assertEqual(eng.evaluate(eng.theorems["check"].wff), True)


if __name__ == "__main__":
    unittest.main()
