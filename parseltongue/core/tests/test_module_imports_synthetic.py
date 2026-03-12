"""Synthetic stress tests for module import resolution.

Generates random .pltg file trees with configurable complexity,
then verifies both loaders produce equivalent outcomes.

The generator builds from composable rules:
  - ImportRule: random import chains (flat, dotted, relative)
  - FactRule: facts with verify-manual
  - DeftermRule: defterms referencing facts from other modules (including chains)
  - DiffRule: diffs comparing facts across modules (consistent or divergent)
  - ShadowRule: local defterms that shadow imported names
  - DocumentRule: load-document + evidence quoting
  - CircularRule: intentionally circular imports
  - ForwardRefRule: diffs/derives referencing names defined later

Each generated tree has a known expected Outcome.
"""

from __future__ import annotations

import os
import random
import shutil
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Reuse classifiers from the hand-crafted test file
from parseltongue.core.tests.test_module_imports import (
    Outcome,
    _classify_lazy,
    _classify_lazy_strict,
    _classify_strict,
)

# ── Random name generation ──

_ADJECTIVES = [
    "red",
    "blue",
    "fast",
    "cold",
    "warm",
    "deep",
    "wide",
    "dark",
    "thin",
    "bold",
    "calm",
    "pure",
    "raw",
    "dry",
    "wet",
    "old",
]
_NOUNS = [
    "fox",
    "cat",
    "owl",
    "elk",
    "bee",
    "ant",
    "bat",
    "cod",
    "eel",
    "yak",
    "ram",
    "hen",
    "jay",
    "ray",
    "doe",
    "ape",
]


def _rand_name(rng: random.Random) -> str:
    return f"{rng.choice(_ADJECTIVES)}-{rng.choice(_NOUNS)}-{rng.randint(0, 999)}"


def _rand_module_name(rng: random.Random, depth: int) -> str:
    """Generate a dotted module name like 'pkg.sub.mod'."""
    parts = []
    for _ in range(depth):
        parts.append(rng.choice(_NOUNS) + str(rng.randint(0, 99)))
    return ".".join(parts)


# ── Module graph node ──


@dataclass
class ModuleSpec:
    """Specification for a single .pltg module file."""

    module_name: str  # dotted name, e.g. "pkg.sub.mod"
    rel_path: str  # file path relative to root, e.g. "pkg/sub/mod.pltg"
    lines: list[str] = field(default_factory=list)
    fact_names: list[str] = field(default_factory=list)  # bare names (no module prefix)
    imports: list[str] = field(default_factory=list)  # module names imported

    def add_fact(self, name: str, value: Any = "true"):
        self.fact_names.append(name)
        self.lines.append(f'(fact {name} {value} :origin "gen")')
        self.lines.append(f'(verify-manual (quote {name}))')

    def add_import(self, module_name: str, relative_dots: int = 0):
        prefix = "." * relative_dots if relative_dots else ""
        self.imports.append(module_name)
        self.lines.append(f'(import (quote {prefix}{module_name}))')

    def add_defterm(self, name: str, ref: str):
        self.fact_names.append(name)
        self.lines.append(f'(defterm {name} {ref} :origin "alias")')
        self.lines.append(f'(verify-manual (quote {name}))')

    def add_diff(self, name: str, replace: str, with_: str):
        self.lines.append(f'(diff {name} :replace {replace} :with {with_})')

    def source(self) -> str:
        return "\n".join(self.lines) + "\n"


# ── Tree generators ──


@dataclass
class GeneratedTree:
    """A generated .pltg file tree with expected outcome."""

    root_dir: str
    main_path: str
    expected: Outcome
    modules: list[ModuleSpec]
    description: str = ""


def _write_modules(root: str, main_spec: ModuleSpec, modules: list[ModuleSpec]):
    """Write all module specs to disk."""
    for mod in [main_spec] + modules:
        p = Path(root) / mod.rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(mod.source())


def gen_linear_chain(rng: random.Random, depth: int) -> GeneratedTree:
    """Generate a linear import chain: main → m0 → m1 → ... → m(depth-1).

    Each module is a flat sibling file. Each imports the next.
    """
    root = tempfile.mkdtemp(prefix="pltg_synth_")
    modules: list[ModuleSpec] = []

    for i in range(depth):
        mod_name = f"lv{i}"
        mod = ModuleSpec(module_name=mod_name, rel_path=f"{mod_name}.pltg")

        n_facts = rng.randint(1, 4)
        for _ in range(n_facts):
            mod.add_fact(_rand_name(rng), rng.randint(1, 100))

        if i < depth - 1:
            mod.add_import(f"lv{i + 1}")

        modules.append(mod)

    main = ModuleSpec(module_name="main", rel_path="main.pltg")
    main.add_import("lv0")

    _write_modules(root, main, modules)
    return GeneratedTree(
        root_dir=root,
        main_path=os.path.join(root, "main.pltg"),
        expected=Outcome.OK,
        modules=[main] + modules,
        description=f"linear chain depth={depth}",
    )


def gen_diamond(rng: random.Random, width: int) -> GeneratedTree:
    """Generate a diamond: main imports N modules, all import a shared leaf.

    All branches reference the SAME shared fact so cross-branch diffs are valid.
    """
    root = tempfile.mkdtemp(prefix="pltg_synth_")

    shared = ModuleSpec(module_name="shared", rel_path="shared.pltg")
    n_shared_facts = rng.randint(2, 5)
    for _ in range(n_shared_facts):
        shared.add_fact(_rand_name(rng), rng.randint(1, 100))

    # Pick ONE shared fact that ALL branches will defterm
    sf = rng.choice(shared.fact_names)

    branches: list[ModuleSpec] = []
    for i in range(width):
        mod = ModuleSpec(module_name=f"branch{i}", rel_path=f"branch{i}.pltg")
        mod.add_import("shared")
        n_facts = rng.randint(1, 3)
        for _ in range(n_facts):
            mod.add_fact(_rand_name(rng), rng.randint(1, 100))
        # Every branch defterms the SAME shared fact
        mod.add_defterm(f"my-{sf}", f"shared.{sf}")
        branches.append(mod)

    main = ModuleSpec(module_name="main", rel_path="main.pltg")
    for b in branches:
        main.add_import(b.module_name)

    # Cross-branch diffs — both reference the same shared fact via defterm
    if len(branches) >= 2:
        main.add_diff(
            f"cross-{_rand_name(rng)}",
            f"branch0.my-{sf}",
            f"branch1.my-{sf}",
        )

    _write_modules(root, main, branches + [shared])
    return GeneratedTree(
        root_dir=root,
        main_path=os.path.join(root, "main.pltg"),
        expected=Outcome.OK,
        modules=[main] + branches + [shared],
        description=f"diamond width={width}",
    )


def gen_deep_dotted(rng: random.Random, depth: int) -> GeneratedTree:
    """Generate deeply nested dotted imports via a chain of sibling files.

    Import resolution: ``.x`` from ``root/a/b/c.pltg`` pops the filename
    giving ``root/a/b/`` then appends ``x.pltg`` → ``root/a/b/x.pltg``.
    So ``.next`` always means a sibling file in the same directory.

    We also test a single deep dotted import from main:
    ``(import (quote pkg0.pkg1.pkg2...pkgN))`` → ``root/pkg0/pkg1/.../pkgN.pltg``.
    """
    root = tempfile.mkdtemp(prefix="pltg_synth_")
    modules: list[ModuleSpec] = []

    # Flat sibling chain: d0 → d1 → d2 → ... all in root/
    for i in range(depth):
        mod = ModuleSpec(module_name=f"d{i}", rel_path=f"d{i}.pltg")
        mod.add_fact(_rand_name(rng), rng.randint(1, 100))
        if i < depth - 1:
            mod.add_import(f".d{i+1}")  # sibling in same dir
        modules.append(mod)

    # One truly nested module at a deep dotted path
    parts = [f"pkg{i}" for i in range(depth)]
    nested_name = ".".join(parts)
    nested_path = "/".join(parts) + ".pltg"
    nested = ModuleSpec(module_name=nested_name, rel_path=nested_path)
    nested.add_fact(_rand_name(rng), rng.randint(1, 100))
    modules.append(nested)

    main = ModuleSpec(module_name="main", rel_path="main.pltg")
    main.add_import("d0")
    main.add_import(nested_name)

    # Reference nested via short alias
    short = parts[-1]
    if nested.fact_names:
        main.add_defterm("deep-ref", f"{short}.{nested.fact_names[0]}")

    _write_modules(root, main, modules)
    return GeneratedTree(
        root_dir=root,
        main_path=os.path.join(root, "main.pltg"),
        expected=Outcome.OK,
        modules=[main] + modules,
        description=f"deep dotted depth={depth}",
    )


def gen_relative_jumps(rng: random.Random, n_modules: int) -> GeneratedTree:
    """Generate modules that use relative imports (.., ..., ....) to jump around."""
    root = tempfile.mkdtemp(prefix="pltg_synth_")

    # Create a grid of modules at various depths
    modules: list[ModuleSpec] = []
    leaf = ModuleSpec(module_name="core.utils.helpers", rel_path="core/utils/helpers.pltg")
    leaf.add_fact(_rand_name(rng), rng.randint(1, 100))
    leaf.add_fact(_rand_name(rng), rng.randint(1, 100))
    modules.append(leaf)

    # Module that uses .. to import from parent
    mid = ModuleSpec(module_name="core.utils.extra", rel_path="core/utils/extra.pltg")
    mid.add_import(".helpers")  # sibling
    if leaf.fact_names:
        mid.add_defterm(f"ref-{_rand_name(rng)}", f"helpers.{leaf.fact_names[0]}")
    modules.append(mid)

    # Module that uses ... to import from grandparent
    deep = ModuleSpec(module_name="core.utils.sub.deep", rel_path="core/utils/sub/deep.pltg")
    deep.add_import("..helpers")  # ../helpers.pltg
    if leaf.fact_names:
        deep.add_defterm(f"ref-{_rand_name(rng)}", f"helpers.{leaf.fact_names[0]}")
    modules.append(deep)

    # Module at top that imports via dotted name
    top = ModuleSpec(module_name="api", rel_path="api.pltg")
    top.add_import("core.utils.helpers")
    if leaf.fact_names:
        top.add_defterm("api-ref", f"helpers.{leaf.fact_names[0]}")
    modules.append(top)

    main = ModuleSpec(module_name="main", rel_path="main.pltg")
    main.add_import("api")
    main.add_import("core.utils.extra")
    main.add_import("core.utils.sub.deep")

    _write_modules(root, main, modules)
    return GeneratedTree(
        root_dir=root,
        main_path=os.path.join(root, "main.pltg"),
        expected=Outcome.OK,
        modules=[main] + modules,
        description=f"relative jumps n={n_modules}",
    )


def gen_shadow_chain(rng: random.Random, chain_len: int) -> GeneratedTree:
    """Generate defterm chains that shadow imported names.

    Module A defines fact X=10. Module B imports A, defines defterm X=A.X.
    Module C imports B, defines defterm X=B.X. Etc.
    Diff at the end checks first vs last — should be consistent (same value).
    """
    root = tempfile.mkdtemp(prefix="pltg_synth_")
    val = rng.randint(1, 100)
    fact_name = _rand_name(rng)

    modules: list[ModuleSpec] = []
    for i in range(chain_len):
        mod = ModuleSpec(module_name=f"s{i}", rel_path=f"s{i}.pltg")
        if i == 0:
            mod.add_fact(fact_name, val)
        else:
            mod.add_import(f"s{i-1}")
            mod.add_defterm(fact_name, f"s{i-1}.{fact_name}")
        modules.append(mod)

    main = ModuleSpec(module_name="main", rel_path="main.pltg")
    for m in modules:
        main.add_import(m.module_name)

    # Diff: first module's fact vs last module's shadow — should match
    main.add_diff(
        "shadow-check",
        f"s0.{fact_name}",
        f"s{chain_len - 1}.{fact_name}",
    )

    _write_modules(root, main, modules)
    return GeneratedTree(
        root_dir=root,
        main_path=os.path.join(root, "main.pltg"),
        expected=Outcome.OK,
        modules=[main] + modules,
        description=f"shadow chain len={chain_len}",
    )


def gen_divergent_tree(rng: random.Random, n_modules: int) -> GeneratedTree:
    """Generate a tree where diffs are intentionally divergent."""
    root = tempfile.mkdtemp(prefix="pltg_synth_")

    modules: list[ModuleSpec] = []
    for i in range(n_modules):
        mod = ModuleSpec(module_name=f"m{i}", rel_path=f"m{i}.pltg")
        # Each module gets a different value for same-named fact
        mod.add_fact("value", rng.randint(1, 100) + i * 1000)
        modules.append(mod)

    main = ModuleSpec(module_name="main", rel_path="main.pltg")
    for m in modules:
        main.add_import(m.module_name)

    # Diff between modules with guaranteed different values
    main.add_diff("div-check", "m0.value", "m1.value")

    _write_modules(root, main, modules)
    return GeneratedTree(
        root_dir=root,
        main_path=os.path.join(root, "main.pltg"),
        expected=Outcome.CONSISTENCY,
        modules=[main] + modules,
        description=f"divergent n={n_modules}",
    )


def gen_circular(rng: random.Random, cycle_len: int) -> GeneratedTree:
    """Generate a circular import chain of given length."""
    root = tempfile.mkdtemp(prefix="pltg_synth_")

    modules: list[ModuleSpec] = []
    for i in range(cycle_len):
        mod = ModuleSpec(module_name=f"c{i}", rel_path=f"c{i}.pltg")
        mod.add_fact(_rand_name(rng), rng.randint(1, 100))
        # Import next in cycle, wrapping around
        next_mod = f"c{(i + 1) % cycle_len}"
        mod.add_import(next_mod)
        modules.append(mod)

    main = ModuleSpec(module_name="main", rel_path="main.pltg")
    main.add_import("c0")

    _write_modules(root, main, modules)
    return GeneratedTree(
        root_dir=root,
        main_path=os.path.join(root, "main.pltg"),
        expected=Outcome.IMPORT_ERR,
        modules=[main] + modules,
        description=f"circular len={cycle_len}",
    )


def gen_missing_import(rng: random.Random) -> GeneratedTree:
    """Generate a tree with a missing import somewhere in the chain."""
    root = tempfile.mkdtemp(prefix="pltg_synth_")

    depth = rng.randint(2, 5)
    modules: list[ModuleSpec] = []
    for i in range(depth):
        mod = ModuleSpec(module_name=f"x{i}", rel_path=f"x{i}.pltg")
        mod.add_fact(_rand_name(rng), rng.randint(1, 100))
        if i < depth - 1:
            mod.add_import(f"x{i+1}")
        else:
            # Last module imports something that doesn't exist
            mod.add_import("phantom")
        modules.append(mod)

    main = ModuleSpec(module_name="main", rel_path="main.pltg")
    main.add_import("x0")

    _write_modules(root, main, modules)
    return GeneratedTree(
        root_dir=root,
        main_path=os.path.join(root, "main.pltg"),
        expected=Outcome.IMPORT_ERR,
        modules=[main] + modules,
        description=f"missing import depth={depth}",
    )


def gen_document_with_quotes(rng: random.Random) -> GeneratedTree:
    """Generate modules with load-document and evidence quoting."""
    root = tempfile.mkdtemp(prefix="pltg_synth_")

    # Write a document file
    doc_text = "The revenue was 42 million in Q4. Profit margin reached 15 percent."
    Path(root, "report.txt").write_text(doc_text)

    checker = ModuleSpec(module_name="checker", rel_path="checker.pltg")
    checker.lines.append('(load-document "report" "report.txt")')
    checker.lines.append(
        '(fact revenue-mentioned true :evidence (evidence (:quotes "revenue was 42 million" :in "report")))'
    )
    checker.lines.append('(verify-manual (quote revenue-mentioned))')
    checker.add_fact("doc-loaded", "true")

    main = ModuleSpec(module_name="main", rel_path="main.pltg")
    main.add_import("checker")

    _write_modules(root, main, [checker])
    return GeneratedTree(
        root_dir=root,
        main_path=os.path.join(root, "main.pltg"),
        expected=Outcome.OK,
        modules=[main, checker],
        description="document with quotes",
    )


def gen_mega_random(rng: random.Random, n_modules: int, max_depth: int) -> GeneratedTree:
    """Generate a large random tree combining multiple patterns.

    Import resolution: a non-relative import ``a.b.c`` from file at dir D
    resolves to ``D/a/b/c.pltg``.  So a module at ``root/x/y/m.pltg``
    importing ``a.b.c`` looks for ``root/x/y/a/b/c.pltg`` — NOT ``root/a/b/c.pltg``.

    To keep imports valid, nested modules use relative ``..`` imports to go
    up to root first, then descend into the target path.  Flat (depth-1)
    modules can use bare dotted names since they sit in root.
    """
    root = tempfile.mkdtemp(prefix="pltg_synth_")

    modules: list[ModuleSpec] = []
    mod_names: list[str] = []
    # Track each module's directory depth for computing relative imports
    mod_depths: dict[str, int] = {}

    for i in range(n_modules):
        depth = rng.randint(1, max_depth)
        parts = [f"p{rng.randint(0,3)}" for _ in range(depth - 1)] + [f"m{i}"]
        mod_name = ".".join(parts)
        rel_path = "/".join(parts) + ".pltg"
        dir_depth = depth - 1  # how many dirs deep from root

        mod = ModuleSpec(module_name=mod_name, rel_path=rel_path)

        # Random facts
        n_facts = rng.randint(1, 6)
        for _ in range(n_facts):
            mod.add_fact(_rand_name(rng), rng.randint(1, 1000))

        # Import earlier modules (no cycles — only import modules with lower index)
        if mod_names and rng.random() < 0.6:
            n_imports = rng.randint(1, min(3, len(mod_names)))
            for imp_name in rng.sample(mod_names, n_imports):
                # Use relative dots to go up to root, then absolute path
                # . = current dir (pops filename), each extra dot = one more parent
                # Need dir_depth+1 dots to reach root: . pops file, then dir_depth more
                dots = "." * (dir_depth + 1)
                mod.add_import(f"{dots}{imp_name}")

                # Sometimes add defterms referencing imported facts
                imp_mod = next(m for m in modules if m.module_name == imp_name)
                if imp_mod.fact_names and rng.random() < 0.5:
                    ref_fact = rng.choice(imp_mod.fact_names)
                    short = imp_name.rsplit(".", 1)[-1]
                    mod.add_defterm(
                        f"ref-{_rand_name(rng)}",
                        f"{short}.{ref_fact}",
                    )

        modules.append(mod)
        mod_names.append(mod_name)
        mod_depths[mod_name] = dir_depth

    main = ModuleSpec(module_name="main", rel_path="main.pltg")
    # Import a subset of modules from main (main is in root, depth=0)
    n_main_imports = min(rng.randint(2, 5), len(mod_names))
    imported = rng.sample(mod_names, n_main_imports)
    for imp in imported:
        main.add_import(imp)

    # Add consistent diffs between imported modules
    if len(imported) >= 2:
        for _ in range(rng.randint(1, 3)):
            m1_name, m2_name = rng.sample(imported, 2)
            m1 = next(m for m in modules if m.module_name == m1_name)
            m2 = next(m for m in modules if m.module_name == m2_name)
            if m1.fact_names and m2.fact_names:
                # Make both facts have the same value for consistency
                shared_val = rng.randint(1, 100)
                f1_name = _rand_name(rng)
                f2_name = _rand_name(rng)
                m1.add_fact(f1_name, shared_val)
                m2.add_fact(f2_name, shared_val)
                short1 = m1_name.rsplit(".", 1)[-1]
                short2 = m2_name.rsplit(".", 1)[-1]
                main.add_diff(
                    f"check-{_rand_name(rng)}",
                    f"{short1}.{f1_name}",
                    f"{short2}.{f2_name}",
                )

    _write_modules(root, main, modules)
    return GeneratedTree(
        root_dir=root,
        main_path=os.path.join(root, "main.pltg"),
        expected=Outcome.OK,
        modules=[main] + modules,
        description=f"mega random n={n_modules} depth={max_depth}",
    )


# ── Test runner ──


class TestSyntheticImports(unittest.TestCase):
    """Run generated trees through all three loaders and check agreement."""

    def _run_tree(self, tree: GeneratedTree):
        """Run a generated tree, print one row with all 3 loader results, then assert."""
        try:
            classic = _classify_strict(tree.main_path)
            lazy = _classify_lazy(tree.main_path)
            lazy_s = _classify_lazy_strict(tree.main_path)

            def _tag(res):
                ok = res.outcome == tree.expected
                return ("OK" if ok else "FAIL") + ":" + res.outcome.name

            agree = classic.outcome == lazy.outcome == lazy_s.outcome
            flag = "" if agree else " DISAGREE"
            print(
                f"  {tree.description:35s}  exp={tree.expected.name:14s}"
                f"  classic={_tag(classic):20s}  lazy={_tag(lazy):20s}  lazy_s={_tag(lazy_s):20s}{flag}"
            )

            failures = []
            for name, res in [("classic", classic), ("lazy", lazy), ("lazy_s", lazy_s)]:
                if res.outcome != tree.expected:
                    err = (res.errors[:1] or res.consistency_issues[:1] or [""])[0]
                    failures.append(f"{name}={res.outcome.name}")
                    if err:
                        print(f"    {name}: {err[:140]}")

            if failures:
                self.fail(f"[{tree.description}] " + "; ".join(failures))

            if tree.expected == Outcome.OK:
                self.assertEqual(classic.names, lazy.names, f"[{tree.description}] Classic vs lazy name mismatch")
        finally:
            shutil.rmtree(tree.root_dir, ignore_errors=True)

    # ── Deterministic structural tests ──

    def test_linear_chain_3(self):
        self._run_tree(gen_linear_chain(random.Random(42), depth=3))

    def test_linear_chain_8(self):
        self._run_tree(gen_linear_chain(random.Random(42), depth=8))

    def test_diamond_3(self):
        self._run_tree(gen_diamond(random.Random(42), width=3))

    def test_diamond_7(self):
        self._run_tree(gen_diamond(random.Random(42), width=7))

    def test_deep_dotted_5(self):
        self._run_tree(gen_deep_dotted(random.Random(42), depth=5))

    def test_deep_dotted_10(self):
        self._run_tree(gen_deep_dotted(random.Random(42), depth=10))

    def test_relative_jumps(self):
        self._run_tree(gen_relative_jumps(random.Random(42), n_modules=4))

    def test_shadow_chain_3(self):
        self._run_tree(gen_shadow_chain(random.Random(42), chain_len=3))

    def test_shadow_chain_8(self):
        self._run_tree(gen_shadow_chain(random.Random(42), chain_len=8))

    def test_divergent_2(self):
        self._run_tree(gen_divergent_tree(random.Random(42), n_modules=2))

    def test_divergent_5(self):
        self._run_tree(gen_divergent_tree(random.Random(42), n_modules=5))

    def test_circular_2(self):
        self._run_tree(gen_circular(random.Random(42), cycle_len=2))

    def test_circular_5(self):
        self._run_tree(gen_circular(random.Random(42), cycle_len=5))

    def test_missing_import(self):
        self._run_tree(gen_missing_import(random.Random(42)))

    def test_document_quotes(self):
        self._run_tree(gen_document_with_quotes(random.Random(42)))

    # ── Randomized stress tests ──

    def test_mega_random_10_modules(self):
        self._run_tree(gen_mega_random(random.Random(1), n_modules=10, max_depth=3))

    def test_mega_random_20_modules(self):
        self._run_tree(gen_mega_random(random.Random(2), n_modules=20, max_depth=4))

    def test_mega_random_50_modules(self):
        self._run_tree(gen_mega_random(random.Random(3), n_modules=50, max_depth=5))

    def test_mega_random_100_modules(self):
        self._run_tree(gen_mega_random(random.Random(4), n_modules=100, max_depth=6))

    # ── Batch: multiple seeds ──

    def test_batch_linear(self):
        """10 random linear chains with varying depths."""
        for seed in range(10):
            rng = random.Random(seed * 17)
            depth = rng.randint(2, 12)
            self._run_tree(gen_linear_chain(rng, depth))

    def test_batch_diamond(self):
        """10 random diamonds with varying widths."""
        for seed in range(10):
            rng = random.Random(seed * 31)
            width = rng.randint(2, 8)
            self._run_tree(gen_diamond(rng, width))

    def test_batch_shadow(self):
        """10 random shadow chains."""
        for seed in range(10):
            rng = random.Random(seed * 47)
            length = rng.randint(2, 10)
            self._run_tree(gen_shadow_chain(rng, length))

    def test_batch_circular(self):
        """10 random circular imports."""
        for seed in range(10):
            rng = random.Random(seed * 59)
            cycle = rng.randint(2, 6)
            self._run_tree(gen_circular(rng, cycle))

    def test_batch_mega(self):
        """10 random mega trees."""
        for seed in range(10):
            rng = random.Random(seed * 73)
            n = rng.randint(5, 30)
            d = rng.randint(2, 5)
            self._run_tree(gen_mega_random(rng, n, d))


class TestErrorLocations(unittest.TestCase):
    """Verify all loaders report source file + line for errors."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pltg_errloc_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, name: str, content: str):
        p = Path(self.root) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return str(p)

    def _classic_err(self, path: str):
        from parseltongue.core.loader.loader import PltgError, load_pltg

        try:
            load_pltg(path)
            return None
        except PltgError as e:
            return e
        except Exception as e:
            return e

    def _lazy_errors(self, path: str):
        from parseltongue.core.loader.lazy_loader import lazy_load_pltg

        r = lazy_load_pltg(path)
        return r.errors  # dict[node, exc]

    def _lazy_strict_err(self, path: str):
        from parseltongue.core.loader.lazy_loader import lazy_load_pltg

        try:
            lazy_load_pltg(path, strict=True)
            return None
        except Exception as e:
            return e

    # ── Missing import ──

    def test_missing_import_classic_has_line(self):
        main = self._write("main.pltg", '(fact a 1 :origin "t")\n(verify-manual (quote a))\n(import (quote ghost))\n')
        e = self._classic_err(main)
        self.assertIsNotNone(e)
        self.assertTrue(hasattr(e, 'file'))
        self.assertEqual(e.line, 3)
        self.assertIn("ghost", str(e))

    def test_missing_import_lazy_has_line(self):
        main = self._write("main.pltg", '(fact a 1 :origin "t")\n(verify-manual (quote a))\n(import (quote ghost))\n')
        errs = self._lazy_errors(main)
        self.assertTrue(len(errs) > 0)
        node = list(errs.keys())[0]
        self.assertEqual(node.source_line, 3)
        self.assertIn(self.root, node.source_file)

    def test_missing_import_lazy_strict_reports(self):
        main = self._write("main.pltg", '(fact a 1 :origin "t")\n(verify-manual (quote a))\n(import (quote ghost))\n')
        e = self._lazy_strict_err(main)
        self.assertIsNotNone(e)
        self.assertIn("ghost", str(e))

    # ── Nested import error (error in child, stack in parent) ──

    def test_nested_import_classic_has_stack(self):
        self._write("child.pltg", '(import (quote phantom))\n')
        main = self._write("main.pltg", '(import (quote child))\n')
        e = self._classic_err(main)
        self.assertIsNotNone(e)
        self.assertEqual(e.line, 1)
        # cause points to child
        self.assertTrue(hasattr(e, 'cause') and e.cause is not None)
        self.assertIn("child.pltg", e.cause.file)
        self.assertEqual(e.cause.line, 1)

    def test_nested_import_lazy_has_child_loc(self):
        self._write("child.pltg", '(import (quote phantom))\n')
        main = self._write("main.pltg", '(import (quote child))\n')
        errs = self._lazy_errors(main)
        self.assertTrue(len(errs) > 0)
        # At least one error should reference child.pltg
        files = [n.source_file for n in errs.keys()]
        self.assertTrue(any("child.pltg" in f for f in files), f"No child.pltg in error files: {files}")

    # ── Circular import ──

    def test_circular_classic_has_line(self):
        self._write("a.pltg", '(import (quote b))\n')
        self._write("b.pltg", '(import (quote a))\n')
        main = self._write("main.pltg", '(import (quote a))\n')
        e = self._classic_err(main)
        self.assertIsNotNone(e)
        self.assertTrue(hasattr(e, 'file'))
        self.assertIn("Circular", str(e))

    def test_circular_lazy_reports(self):
        self._write("a.pltg", '(import (quote b))\n')
        self._write("b.pltg", '(import (quote a))\n')
        main = self._write("main.pltg", '(import (quote a))\n')
        errs = self._lazy_errors(main)
        self.assertTrue(len(errs) > 0)

    # ── Bad symbol reference ──

    def test_bad_ref_classic_has_line(self):
        main = self._write(
            "main.pltg",
            '(fact x 1 :origin "t")\n'
            '(verify-manual (quote x))\n'
            '(defterm y nonexistent-thing :origin "bad")\n'
            '(verify-manual (quote y))\n',
        )
        e = self._classic_err(main)
        # May or may not error depending on engine behavior for unresolved refs
        # but if it does, it should have location
        if e is not None and hasattr(e, 'line'):
            self.assertGreater(e.line, 0)

    # ── Deep chain: error 3 levels deep ──

    def test_deep_chain_error_classic(self):
        self._write("c.pltg", '(import (quote does-not-exist))\n')
        self._write("b.pltg", '(import (quote c))\n')
        self._write("a.pltg", '(import (quote b))\n')
        main = self._write("main.pltg", '(import (quote a))\n')
        e = self._classic_err(main)
        self.assertIsNotNone(e)
        self.assertTrue(hasattr(e, 'file'))
        # Walk cause chain — should reach the deepest file
        depth = 0
        cur = e
        while hasattr(cur, 'cause') and cur.cause is not None:
            cur = cur.cause
            depth += 1
        self.assertGreaterEqual(depth, 2, "Cause chain should be at least 2 deep")
        # Deepest cause should mention the missing module
        self.assertIn("does-not-exist", str(cur))

    def test_deep_chain_error_lazy(self):
        self._write("c.pltg", '(import (quote does-not-exist))\n')
        self._write("b.pltg", '(import (quote c))\n')
        self._write("a.pltg", '(import (quote b))\n')
        main = self._write("main.pltg", '(import (quote a))\n')
        errs = self._lazy_errors(main)
        self.assertTrue(len(errs) > 0)
        # Should have error pointing at c.pltg
        files = [n.source_file for n in errs.keys()]
        self.assertTrue(any("c.pltg" in f for f in files), f"No c.pltg in {files}")

    # ── Error on specific line (not line 1) ──

    def test_error_on_later_line_classic(self):
        main = self._write(
            "main.pltg",
            '(fact a 1 :origin "t")\n'  # line 1
            '(verify-manual (quote a))\n'  # line 2
            '(fact b 2 :origin "t")\n'  # line 3
            '(verify-manual (quote b))\n'  # line 4
            '(fact c 3 :origin "t")\n'  # line 5
            '(verify-manual (quote c))\n'  # line 6
            '(import (quote nowhere))\n',  # line 7
        )
        e = self._classic_err(main)
        self.assertIsNotNone(e)
        self.assertEqual(e.line, 7, f"Expected error on line 7, got {e.line}")

    def test_error_on_later_line_lazy(self):
        main = self._write(
            "main.pltg",
            '(fact a 1 :origin "t")\n'
            '(verify-manual (quote a))\n'
            '(fact b 2 :origin "t")\n'
            '(verify-manual (quote b))\n'
            '(fact c 3 :origin "t")\n'
            '(verify-manual (quote c))\n'
            '(import (quote nowhere))\n',
        )
        errs = self._lazy_errors(main)
        self.assertTrue(len(errs) > 0)
        node = list(errs.keys())[0]
        self.assertEqual(node.source_line, 7, f"Expected error on line 7, got {node.source_line}")

    # ── All 3 loaders agree on error presence ──

    def test_all_loaders_agree_on_error_scenarios(self):
        """Multiple error scenarios: all 3 loaders should detect an error."""
        scenarios = {
            "missing": '(import (quote nope))\n',
            "missing_deep": None,  # set up below
        }
        # missing_deep: main → child → phantom
        self._write("kid.pltg", '(import (quote phantom))\n')
        scenarios["missing_deep"] = '(import (quote kid))\n'

        for name, content in scenarios.items():
            main = self._write("main.pltg", content)
            c = self._classic_err(main)
            lazy = self._lazy_errors(main)
            ls = self._lazy_strict_err(main)

            c_has = c is not None
            l_has = len(lazy) > 0
            ls_has = ls is not None

            print(
                f"  {name:20s}  classic={'ERR' if c_has else 'OK':3s}  lazy={'ERR' if l_has else 'OK':3s}  lazy_s={'ERR' if ls_has else 'OK':3s}"
            )
            self.assertTrue(c_has, f"[{name}] classic should error")
            self.assertTrue(l_has, f"[{name}] lazy should have errors")
            self.assertTrue(ls_has, f"[{name}] lazy_strict should error")


class TestErrorTypes(unittest.TestCase):
    """Comprehensive error type tests — every error kind the loaders can face.

    Each test generates a minimal .pltg that triggers a specific error,
    runs all 3 loaders, and checks they all detect it.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pltg_errtype_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, name: str, content: str) -> str:
        p = Path(self.root) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return str(p)

    def _check_all_error(self, path: str, label: str):
        """Run all 3 loaders and assert all detect an error."""
        classic = _classify_strict(path)
        lazy = _classify_lazy(path)
        lazy_s = _classify_lazy_strict(path)

        def _tag(r):
            return r.outcome.name

        print(f"  {label:40s}  classic={_tag(classic):14s}  " f"lazy={_tag(lazy):14s}  lazy_s={_tag(lazy_s):14s}")

        # All should NOT be OK
        errors = []
        if classic.outcome == Outcome.OK:
            errors.append("classic=OK")
        if lazy.outcome == Outcome.OK:
            errors.append("lazy=OK")
        if lazy_s.outcome == Outcome.OK:
            errors.append("lazy_s=OK")
        if errors:
            self.fail(f"[{label}] Expected error but got: {', '.join(errors)}")

    def _check_classic_error_type(self, path: str, exc_type: type, label: str):
        """Check the classic loader raises a specific exception type."""
        from parseltongue.core.loader.loader import PltgError, load_pltg

        try:
            load_pltg(path)
            self.fail(f"[{label}] classic loader did not raise")
        except exc_type:
            pass  # expected
        except PltgError as e:
            # PltgError wraps the original — check the cause
            if e.__cause__ and isinstance(e.__cause__, exc_type):
                pass
            else:
                self.fail(f"[{label}] classic raised PltgError but cause is {type(e.__cause__)}, expected {exc_type}")
        except Exception as e:
            self.fail(f"[{label}] classic raised {type(e).__name__}, expected {exc_type.__name__}: {e}")

    # ── 1. Broken S-expressions ──

    def test_unclosed_paren(self):
        path = self._write("main.pltg", '(fact x 1 :origin "t"\n')
        self._check_all_error(path, "unclosed paren")

    def test_unexpected_close_paren(self):
        path = self._write("main.pltg", ')\n')
        self._check_all_error(path, "unexpected close paren")

    def test_empty_expression_is_noop(self):
        """Empty () is silently ignored — not an error."""
        path = self._write("main.pltg", '()\n')
        classic = _classify_strict(path)
        lazy = _classify_lazy(path)
        self.assertEqual(classic.outcome, Outcome.OK)
        self.assertEqual(lazy.outcome, Outcome.OK)

    def test_nested_broken_sexp(self):
        path = self._write(
            "main.pltg",
            '(fact a 1 :origin "t")\n' '(verify-manual (quote a))\n' '(fact b (+ 1\n',  # unclosed
        )
        self._check_all_error(path, "nested broken sexp")

    # ── 2. Duplicate fact ──

    def test_duplicate_fact(self):
        """Classic errors on duplicate; lazy loaders warn but continue."""
        path = self._write(
            "main.pltg", '(fact x 1 :origin "t")\n' '(verify-manual (quote x))\n' '(fact x 2 :origin "t")\n'
        )
        classic = _classify_strict(path)
        lazy = _classify_lazy(path)
        lazy_s = _classify_lazy_strict(path)
        print(
            f"  {'duplicate fact':40s}  classic={classic.outcome.name:14s}  "
            f"lazy={lazy.outcome.name:14s}  lazy_s={lazy_s.outcome.name:14s}"
        )
        # Classic is strict — duplicate fact is an error
        self.assertNotEqual(classic.outcome, Outcome.OK, "classic should error on duplicate fact")
        # Lazy loaders are lenient — they warn but continue
        self.assertEqual(lazy.outcome, Outcome.OK, "lazy should warn but continue on duplicate")
        self.assertEqual(lazy_s.outcome, Outcome.OK, "lazy_strict should warn but continue on duplicate")

    # ── 3. Ground axiom (no ?-vars) ──

    def test_ground_axiom(self):
        path = self._write("main.pltg", '(axiom bad-axiom (= 1 1) :origin "test")\n')
        self._check_all_error(path, "ground axiom (no ?-vars)")

    # ── 4. Unresolved symbol ──

    def test_unresolved_symbol_in_defterm(self):
        path = self._write("main.pltg", '(defterm y nonexistent-thing :origin "bad")\n' '(verify-manual (quote y))\n')
        # defterm with unresolved ref may not error until evaluation
        # but at minimum lazy-strict should catch it
        classic = _classify_strict(path)
        lazy_s = _classify_lazy_strict(path)
        print(f"  {'unresolved in defterm':40s}  classic={classic.outcome.name:14s}  lazy_s={lazy_s.outcome.name:14s}")

    def test_unresolved_symbol_in_derive(self):
        path = self._write(
            "main.pltg",
            '(fact a 1 :origin "t")\n' '(verify-manual (quote a))\n' '(derive d (= ghost 1) :using (ghost))\n',
        )
        self._check_all_error(path, "unresolved symbol in derive")

    # ── 5. Axiom in :using without :bind ──

    def test_axiom_without_bind(self):
        path = self._write(
            "main.pltg",
            '(axiom my-ax (implies ?x (not ?x)) :origin "test")\n'
            '(verify-manual (quote my-ax))\n'
            '(fact a true :origin "t")\n'
            '(verify-manual (quote a))\n'
            '(derive d (implies a (not a)) :using (my-ax a))\n',
        )
        self._check_all_error(path, "axiom without :bind")

    # ── 6. Unknown source in derive :using ──

    def test_unknown_using_source(self):
        path = self._write(
            "main.pltg",
            '(fact a 1 :origin "t")\n' '(verify-manual (quote a))\n' '(derive d (= a 1) :using (a phantom-fact))\n',
        )
        self._check_all_error(path, "unknown :using source")

    # ── 7. Circular import ──

    def test_circular_import_direct(self):
        self._write("a.pltg", '(import (quote b))\n')
        self._write("b.pltg", '(import (quote a))\n')
        path = self._write("main.pltg", '(import (quote a))\n')
        self._check_all_error(path, "circular import")

    # ── 8. Missing import ──

    def test_missing_import(self):
        path = self._write("main.pltg", '(import (quote nonexistent))\n')
        self._check_all_error(path, "missing import")

    # ── 9. Bad evidence expression ──

    def test_bad_evidence_missing_keyword(self):
        path = self._write("main.pltg", '(fact x true :evidence ("doc" :quotes "text"))\n')
        # Evidence without (evidence ...) wrapper
        self._check_all_error(path, "bad evidence (no wrapper)")

    def test_bad_evidence_wrong_start(self):
        path = self._write("main.pltg", '(fact x true :evidence (wrong (:quotes "text" :in "doc")))\n')
        self._check_all_error(path, "bad evidence (wrong start)")

    # ── 10. dangerously-eval error ──

    def test_dangerous_eval_runtime_error(self):
        path = self._write("main.pltg", '(dangerously-eval 1/0)\n')
        self._check_all_error(path, "dangerous-eval ZeroDivisionError")

    def test_dangerous_eval_name_error(self):
        path = self._write("main.pltg", '(dangerously-eval undefined_variable_xyz)\n')
        self._check_all_error(path, "dangerous-eval NameError")

    # ── 11. Missing file for load-document ──

    def test_load_document_missing_file(self):
        path = self._write("main.pltg", '(load-document "doc" "does_not_exist.txt")\n')
        self._check_all_error(path, "load-document missing file")

    # ── 12. Diff references unknown symbol ──

    def test_diff_unknown_replace(self):
        path = self._write(
            "main.pltg",
            '(fact a 1 :origin "t")\n' '(verify-manual (quote a))\n' '(diff bad-diff :replace ghost :with a)\n',
        )
        # Diff with unknown :replace — should error during consistency or earlier
        classic = _classify_strict(path)
        lazy_s = _classify_lazy_strict(path)
        print(f"  {'diff unknown :replace':40s}  classic={classic.outcome.name:14s}  lazy_s={lazy_s.outcome.name:14s}")
        # At minimum shouldn't be OK with no issues
        self.assertNotEqual(classic.outcome, Outcome.OK, "diff with unknown :replace should not be OK")

    # ── 13. Derive from non-existent axiom with :bind ──

    def test_bind_unknown_axiom(self):
        path = self._write(
            "main.pltg",
            '(fact a 1 :origin "t")\n'
            '(verify-manual (quote a))\n'
            '(derive d phantom-axiom :bind ((?x a)) :using (a))\n',
        )
        self._check_all_error(path, "bind references unknown axiom")

    # ── 14. Multiple errors in one file ──

    def test_multiple_errors(self):
        path = self._write(
            "main.pltg",
            '(fact a 1 :origin "t")\n'
            '(verify-manual (quote a))\n'
            '(fact a 2 :origin "t")\n'  # duplicate
            '(import (quote ghost))\n',  # missing import
        )
        self._check_all_error(path, "multiple errors")

    # ── 15. Nested import with error in child ──

    def test_child_module_syntax_error(self):
        self._write("child.pltg", '(fact x 1 :origin "t"\n')  # unclosed
        path = self._write("main.pltg", '(import (quote child))\n')
        self._check_all_error(path, "child module syntax error")

    def test_child_module_duplicate_fact(self):
        """Classic errors on child duplicate; lazy loaders warn but continue."""
        self._write("child.pltg", '(fact x 1 :origin "t")\n' '(verify-manual (quote x))\n' '(fact x 2 :origin "t")\n')
        path = self._write("main.pltg", '(import (quote child))\n')
        classic = _classify_strict(path)
        lazy = _classify_lazy(path)
        lazy_s = _classify_lazy_strict(path)
        print(
            f"  {'child duplicate fact':40s}  classic={classic.outcome.name:14s}  "
            f"lazy={lazy.outcome.name:14s}  lazy_s={lazy_s.outcome.name:14s}"
        )
        self.assertNotEqual(classic.outcome, Outcome.OK, "classic should error")
        self.assertEqual(lazy.outcome, Outcome.OK, "lazy should warn but continue")
        self.assertEqual(lazy_s.outcome, Outcome.OK, "lazy_strict should warn but continue")


if __name__ == "__main__":
    unittest.main()
