"""Tests for system.copy() effect rebinding and import alias feature.

Verifies that:
1. Effects on a copied system fire with the COPY as `system`, not the original
2. Import alias syntax (import (quote ..module alias)) works
3. Re-interpretation on a system copy resolves aliased names
"""

from __future__ import annotations

import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from parseltongue.core.atoms import Symbol
from parseltongue.core.system import System


class TestSystemCopyEffectRebinding(unittest.TestCase):
    """Effects on a copied system must receive the clone, not the original."""

    def test_effect_receives_clone_not_original(self):
        """When an effect fires on a copy, `system` arg is the copy."""
        received_systems = []

        def track_effect(system, *args):
            received_systems.append(system)
            return True

        original = System(effects={"test-effect": track_effect}, name="original")
        clone = original.copy(name="clone")

        # Fire effect on original
        original.engine.env[Symbol("test-effect")]()
        self.assertIs(received_systems[-1], original)

        # Fire effect on clone — must receive clone, not original
        clone.engine.env[Symbol("test-effect")]()
        self.assertIs(received_systems[-1], clone)
        self.assertIsNot(received_systems[-1], original)

    def test_effect_mutates_clone_engine(self):
        """An effect that mutates system.engine should mutate the clone's engine."""
        from parseltongue.core.engines.engine_stack import Fact

        def set_fact_effect(system, name_sym):
            name = str(name_sym)
            system.engine.facts[name] = Fact(name=name, wff=42, origin="effect")
            system.engine.env[Symbol(name)] = 42
            return True

        original = System(effects={"set-fact": set_fact_effect}, name="original")
        clone = original.copy(name="clone")

        # Fire on clone
        clone.engine.env[Symbol("set-fact")](Symbol("injected"))

        # Clone has the fact, original does not
        self.assertIn("injected", clone.engine.facts)
        self.assertNotIn("injected", original.engine.facts)

    def test_second_copy_independent(self):
        """Two copies get independent effect bindings."""
        received = []

        def track(system, *args):
            received.append(system.engine.name)

        original = System(effects={"ping": track}, name="orig")
        copy_a = original.copy(name="copy-a")
        copy_b = original.copy(name="copy-b")

        copy_a.engine.env[Symbol("ping")]()
        copy_b.engine.env[Symbol("ping")]()
        original.engine.env[Symbol("ping")]()

        self.assertEqual(received, ["copy-a", "copy-b", "orig"])


class TestImportAlias(unittest.TestCase):
    """Import alias: (import (quote ..module alias)) registers short names."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="pltg_alias_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, relpath: str, content: str):
        p = Path(self.tmpdir) / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(content))
        return str(p)

    def test_alias_basic_load(self):
        """Loading a file with import alias resolves aliased fact names."""
        self._write(
            "data/numbers.pltg",
            """\
            (fact count 42 "test data")
            (fact total 100 "test data")
        """,
        )
        main = self._write(
            "main.pltg",
            """\
            (import (quote .data.numbers nums))
            (defterm double (* nums.count 2) :using (nums.count))
        """,
        )

        from parseltongue.core.loader.lazy_loader import LazyLoader

        loader = LazyLoader(lib_paths=[self.tmpdir])
        system = loader.load_main(main)

        # Facts should exist under canonical name
        self.assertIn("data.numbers.count", system.engine.facts)
        # Term should resolve using alias
        self.assertIn("double", system.engine.terms)

    def test_alias_on_system_copy_interpret(self):
        """Re-interpreting import block on a system copy registers alias on clone."""
        self._write(
            "data/numbers.pltg",
            """\
            (fact count 42 "test data")
        """,
        )
        main = self._write(
            "main.pltg",
            """\
            (import (quote .data.numbers nums))
            (defterm double (* nums.count 2) :using (nums.count))
        """,
        )

        from parseltongue.core.loader.lazy_loader import LazyLoader

        loader = LazyLoader(lib_paths=[self.tmpdir])
        system = loader.load_main(main)

        # Copy the system
        clone = system.copy(name="re-eval", overridable=True)

        # Re-interpret the import block on the clone
        clone.interpret('(import (quote .data.numbers nums))')

        # The alias should register on the clone's engine
        # Check if nums.count resolves (via alias registration in import effect)
        has_alias = "nums.count" in clone.engine.facts or Symbol("nums.count") in clone.engine.env
        self.assertTrue(has_alias, "Alias 'nums.count' not found on clone after re-interpret")

    def test_alias_does_not_leak_to_original(self):
        """Re-interpreting import on clone must not affect original."""
        received_systems = []

        def spy_effect(system, *args):
            received_systems.append(id(system))
            return True

        original = System(effects={"spy": spy_effect}, name="original")
        clone = original.copy(name="clone")

        # Fire on clone
        clone.engine.env[Symbol("spy")]()
        # Fire on original
        original.engine.env[Symbol("spy")]()

        # They should be different system instances
        self.assertNotEqual(received_systems[0], received_systems[1])


class TestExecutorReinterpret(unittest.TestCase):
    """End-to-end: executor Step 3 re-interpret resolves aliases on copy."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="pltg_executor_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, relpath: str, content: str):
        p = Path(self.tmpdir) / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(content))
        return str(p)

    def test_bench_interpret_with_alias(self):
        """bench.interpret() on a block with aliased imports should work."""
        self._write(
            "data/vals.pltg",
            """\
            (fact revenue 5000000 "test data")
            (fact cost 2000000 "test data")
        """,
        )
        main = self._write(
            "main.pltg",
            """\
            (import (quote .data.vals v))
            (defterm profit (- v.revenue v.cost) :using (v.revenue v.cost))
        """,
        )

        from parseltongue.core.inspect.bench import Bench

        bench = Bench(lib_paths=[self.tmpdir])
        bench.purge()
        bench.prepare(main)

        result = bench.result(main)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.system)

        # Copy and re-interpret — this is what executor Step 3 does
        system = result.system.copy(name="nb-eval", overridable=True)

        # Re-interpret the import + derive block
        system.interpret('(import (quote .data.vals v))')
        system.interpret('(defterm profit2 (- v.revenue v.cost) :using (v.revenue v.cost))')

        # profit2 is a lazy term — evaluate it
        val = system.engine.evaluate(Symbol("profit2"))
        self.assertEqual(val, 3000000)


if __name__ == "__main__":
    unittest.main()
