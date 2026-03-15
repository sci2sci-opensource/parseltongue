"""Tests for module import resolution and cross-loader behavioral equivalence.

Strategy:
  Generate synthetic .pltg file trees in tmp dirs, then run both loaders
  (strict Loader and LazyLoader) against them.  Classify every outcome
  into one of the behavioural buckets below and assert the two loaders
  agree on the classification.

Behavioural buckets (Items × Layers style):
  OK           — loads cleanly, all names resolved, consistency passes
  IMPORT_ERR   — missing file, circular import
  RESOLVE_ERR  — bare symbol can't be resolved (forward ref, bad alias)
  NAMESPACE_ERR— name registered under wrong prefix
  CONSISTENCY  — loads but diffs diverge or evidence ungrounded
  EFFECT_ERR   — effect (verify-manual, print, etc.) fails at runtime

Each test class generates a directory tree, loads via both loaders,
and asserts equivalent classification.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import textwrap
import unittest
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path


class Outcome(Enum):
    OK = auto()
    IMPORT_ERR = auto()
    RESOLVE_ERR = auto()
    NAMESPACE_ERR = auto()
    CONSISTENCY = auto()
    EFFECT_ERR = auto()


@dataclass
class LoadResult:
    outcome: Outcome
    names: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    consistency_issues: list[str] = field(default_factory=list)


def _classify_strict(path: str) -> LoadResult:
    """Run the strict (non-lazy) loader and classify outcome."""
    from parseltongue.core.loader.loader import PltgError, load_pltg

    try:
        system = load_pltg(path)
    except PltgError as e:
        msg = str(e)
        cause = e.cause or e.__cause__
        if isinstance(cause, (FileNotFoundError, ImportError)):
            return LoadResult(outcome=Outcome.IMPORT_ERR, errors=[msg])
        if "Circular import" in msg or "not found at" in msg:
            return LoadResult(outcome=Outcome.IMPORT_ERR, errors=[msg])
        if "Unknown symbol" in msg or "Unresolved" in msg:
            return LoadResult(outcome=Outcome.RESOLVE_ERR, errors=[msg])
        if "Unknown:" in msg:
            return LoadResult(outcome=Outcome.EFFECT_ERR, errors=[msg])
        return LoadResult(outcome=Outcome.EFFECT_ERR, errors=[msg])
    except (FileNotFoundError, ImportError) as e:
        return LoadResult(outcome=Outcome.IMPORT_ERR, errors=[str(e)])
    except KeyError as e:
        msg = str(e)
        if "Unknown symbol" in msg or "Unresolved" in msg:
            return LoadResult(outcome=Outcome.RESOLVE_ERR, errors=[msg])
        return LoadResult(outcome=Outcome.EFFECT_ERR, errors=[msg])
    except Exception as e:
        return LoadResult(outcome=Outcome.EFFECT_ERR, errors=[str(e)])

    # Loaded OK — check consistency
    engine = system.engine
    names = set(engine.facts) | set(engine.axioms) | set(engine.terms) | set(engine.theorems)
    try:
        report = engine.consistency()
    except KeyError as e:
        return LoadResult(outcome=Outcome.RESOLVE_ERR, names=names, errors=[str(e)])

    from parseltongue.core.engine import IssueType

    real_issues = [i for i in report.issues if i.type != IssueType.NO_EVIDENCE]
    if real_issues:
        issues = [str(i.type.value) for i in real_issues]
        return LoadResult(outcome=Outcome.CONSISTENCY, names=names, consistency_issues=issues)

    return LoadResult(outcome=Outcome.OK, names=names)


def _classify_lazy(path: str) -> LoadResult:
    """Run the lazy loader and classify outcome."""
    from parseltongue.core.loader.lazy_loader import lazy_load_pltg

    result = lazy_load_pltg(path)
    engine = result.system.engine
    names = set(engine.facts) | set(engine.axioms) | set(engine.terms) | set(engine.theorems)

    # Check for import errors (effects that failed)
    import_errors = []
    other_errors = []
    for node, exc in result.errors.items():
        msg = str(exc)
        if isinstance(exc, (FileNotFoundError, ImportError)):
            import_errors.append(msg)
        elif "Unknown:" in msg:
            other_errors.append(msg)
        elif "Unknown symbol" in msg or "Unresolved" in msg:
            other_errors.append(msg)
        else:
            other_errors.append(msg)

    if import_errors:
        return LoadResult(outcome=Outcome.IMPORT_ERR, names=names, errors=import_errors)

    # Errors in directives
    resolve_errors = [e for e in other_errors if "Unknown symbol" in e or "Unresolved" in e or "Unknown:" in e]
    if resolve_errors and not names - {"count-exists"}:
        return LoadResult(outcome=Outcome.RESOLVE_ERR, names=names, errors=resolve_errors)

    # Check consistency
    try:
        lc = result.consistency()
    except KeyError as e:
        return LoadResult(outcome=Outcome.RESOLVE_ERR, names=names, errors=[str(e)])

    from parseltongue.core.engine import IssueType

    real_issues = [i for i in lc.report.issues if i.type != IssueType.NO_EVIDENCE]
    if real_issues:
        issues = [str(i.type.value) for i in real_issues]
        return LoadResult(outcome=Outcome.CONSISTENCY, names=names, consistency_issues=issues)

    if other_errors:
        return LoadResult(outcome=Outcome.EFFECT_ERR, names=names, errors=other_errors)

    return LoadResult(outcome=Outcome.OK, names=names)


def _classify_lazy_strict(path: str) -> LoadResult:
    """Run the lazy loader in strict mode and classify outcome."""
    from parseltongue.core.loader.lazy_loader import lazy_load_pltg

    try:
        result = lazy_load_pltg(path, strict=True)
    except (FileNotFoundError, ImportError) as e:
        return LoadResult(outcome=Outcome.IMPORT_ERR, errors=[str(e)])
    except SystemError as e:
        msg = str(e)
        if "Circular import" in msg or "not found at" in msg:
            return LoadResult(outcome=Outcome.IMPORT_ERR, errors=[msg])
        if "Unknown symbol" in msg or "Unresolved" in msg or "Unknown:" in msg:
            return LoadResult(outcome=Outcome.RESOLVE_ERR, errors=[msg])
        return LoadResult(outcome=Outcome.EFFECT_ERR, errors=[msg])
    except Exception as e:
        return LoadResult(outcome=Outcome.EFFECT_ERR, errors=[str(e)])

    engine = result.system.engine
    names = set(engine.facts) | set(engine.axioms) | set(engine.terms) | set(engine.theorems)

    try:
        lc = result.consistency()
    except KeyError as e:
        return LoadResult(outcome=Outcome.RESOLVE_ERR, names=names, errors=[str(e)])

    from parseltongue.core.engine import IssueType

    real_issues = [i for i in lc.report.issues if i.type != IssueType.NO_EVIDENCE]
    if real_issues:
        issues = [str(i.type.value) for i in real_issues]
        return LoadResult(outcome=Outcome.CONSISTENCY, names=names, consistency_issues=issues)

    return LoadResult(outcome=Outcome.OK, names=names)


def _write_tree(base: str, files: dict[str, str]):
    """Write a dict of {relative_path: content} to base dir."""
    for rel, content in files.items():
        p = Path(base) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(content))


class _TmpDirTestCase(unittest.TestCase):
    """Base class that creates and cleans up a temp directory."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="pltg_import_test_")
        self._orig_dir = os.getcwd()
        os.chdir(self.tmpdir)

    def tearDown(self):
        os.chdir(self._orig_dir)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _main(self, name: str = "main.pltg") -> str:
        return os.path.join(self.tmpdir, name)

    def _assert_loaders_agree(self, path: str, expected: Outcome):
        """All three loader modes must classify to the same outcome."""
        strict = _classify_strict(path)
        lazy = _classify_lazy(path)
        lazy_strict = _classify_lazy_strict(path)

        self.assertEqual(
            strict.outcome,
            expected,
            f"Strict loader: expected {expected}, got {strict.outcome}\n  errors: {strict.errors}",
        )
        self.assertEqual(
            lazy.outcome, expected, f"Lazy loader: expected {expected}, got {lazy.outcome}\n  errors: {lazy.errors}"
        )
        self.assertEqual(
            lazy_strict.outcome,
            expected,
            f"Lazy-strict loader: expected {expected}, got {lazy_strict.outcome}\n  errors: {lazy_strict.errors}",
        )

    def _assert_names_present(self, path: str, expected_names: set[str]):
        """Check that all expected names are registered after loading."""
        lazy = _classify_lazy(path)
        for name in expected_names:
            self.assertIn(name, lazy.names, f"Expected name '{name}' not found in {lazy.names}")


# =====================================================================
# Test classes
# =====================================================================


class TestSimpleImport(_TmpDirTestCase):
    """Basic import: main imports a sibling module."""

    def test_flat_import(self):
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote lib))\n(diff d1 :replace lib.x :with lib.y)',
                "lib.pltg": '(fact x true :origin "test")\n(fact y true :origin "test")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)
        self._assert_names_present(self._main(), {"lib.x", "lib.y"})

    def test_missing_import(self):
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote nonexistent))',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.IMPORT_ERR)


class TestRelativeImports(_TmpDirTestCase):
    """Relative imports with leading dots."""

    def test_single_dot_sibling(self):
        """(import (quote .sibling)) resolves to ./sibling.pltg"""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote sub))',
                "sub.pltg": '(import (quote .helper))\n(defterm combined helper.val :origin "ref")',
                "helper.pltg": '(fact val 42 :origin "test")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)
        self._assert_names_present(self._main(), {"sub.combined", "helper.val"})

    def test_double_dot_parent(self):
        """(import (quote ..lib)) resolves to ../lib.pltg"""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote pkg.entry))',
                "pkg/entry.pltg": '(import (quote ..shared))\n(defterm ref shared.val :origin "ref")',
                "shared.pltg": '(fact val 99 :origin "test")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)

    def test_triple_dot_grandparent(self):
        """(import (quote ...lib)) resolves to ../../lib.pltg"""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote a.b.deep))',
                "a/b/deep.pltg": '(import (quote ...root_lib))\n(defterm ref root_lib.val :origin "ref")',
                "root_lib.pltg": '(fact val 7 :origin "test")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)


class TestDottedModuleNames(_TmpDirTestCase):
    """Dotted module names: (import (quote a.b.c)) → a/b/c.pltg"""

    def test_nested_dotted(self):
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote a.b.c))\n(diff d1 :replace c.x :with c.y)',
                "a/b/c.pltg": '(fact x true :origin "t")\n(fact y true :origin "t")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)
        # Short alias "c" should resolve to "a.b.c"
        self._assert_names_present(self._main(), {"a.b.c.x", "a.b.c.y"})


class TestDeepNesting(_TmpDirTestCase):
    """10-level deep import chain."""

    def test_ten_levels(self):
        files = {}
        # d0/d1/d2/.../d9/mod.pltg — each imports the next level
        path_parts = []
        for i in range(10):
            path_parts.append(f"d{i}")
            dir_path = "/".join(path_parts)
            if i < 9:
                files[f"{dir_path}/mod.pltg"] = (
                    f'(import (quote .d{i+1}.mod))\n' f'(fact level-{i} {i} :origin "depth {i}")'
                )
            else:
                files[f"{dir_path}/mod.pltg"] = f'(fact level-{i} {i} :origin "depth {i}")'

        files["main.pltg"] = '(import (quote d0.mod))'
        _write_tree(self.tmpdir, files)
        self._assert_loaders_agree(self._main(), Outcome.OK)


class TestCircularImport(_TmpDirTestCase):
    """Circular imports must be detected."""

    def test_direct_circular(self):
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote a))',
                "a.pltg": '(import (quote b))',
                "b.pltg": '(import (quote a))',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.IMPORT_ERR)

    def test_self_import(self):
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote main))',
            },
        )
        # Self-import: main file is not in _imported until after _load_source,
        # so importing itself during load triggers circular import detection.
        self._assert_loaders_agree(self._main(), Outcome.IMPORT_ERR)

    def test_triangle_circular(self):
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote a))',
                "a.pltg": '(import (quote b))',
                "b.pltg": '(import (quote c))',
                "c.pltg": '(import (quote a))',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.IMPORT_ERR)


class TestModuleAliasing(_TmpDirTestCase):
    """Module aliasing: re-importing under different name creates alias."""

    def test_alias_resolution(self):
        """Two modules import same file under different names."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": (
                    '(import (quote a))\n' '(import (quote sub.helper))\n' '(diff d1 :replace a.x :with sub.helper.y)'
                ),
                "a.pltg": '(import (quote sub.helper))\n(fact x true :origin "t")',
                "sub/helper.pltg": '(fact y true :origin "t")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)

    def test_short_alias_for_dotted(self):
        """(import (quote std.counting)) creates alias counting → std.counting."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote pkg.utils))\n(diff d1 :replace pkg.utils.a :with pkg.utils.b)',
                "pkg/utils.pltg": '(fact a 1 :origin "t")\n(fact b 1 :origin "t")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)
        self._assert_names_present(self._main(), {"pkg.utils.a", "pkg.utils.b"})


class TestNamespacing(_TmpDirTestCase):
    """Symbol namespacing: definitions get module prefix, references resolve."""

    def test_cross_module_reference(self):
        """Module A defines fact, module B's diff references it."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote a))\n(import (quote b))',
                "a.pltg": '(fact score 100 :origin "t")',
                "b.pltg": '(fact target 100 :origin "t")\n(diff d1 :replace a.score :with target)',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)

    def test_defterm_references_imported_fact(self):
        """defterm in sub-module references fact from another sub-module."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote data))\n(import (quote logic))',
                "data.pltg": '(fact count 5 :origin "t")',
                "logic.pltg": '(defterm my-count data.count :origin "alias")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)
        self._assert_names_present(self._main(), {"logic.my-count", "data.count"})

    def test_verify_manual_in_submodule(self):
        """verify-manual must resolve bare name to namespaced version."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote sub))',
                "sub.pltg": ('(fact x true :origin "manual check")\n' '(verify-manual (quote x))'),
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)

    def test_verify_manual_with_module_prefix(self):
        """verify-manual with already-prefixed name."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote lib))',
                "lib.pltg": (
                    '(import (quote .helper))\n'
                    '(defterm ref helper.val :origin "alias")\n'
                    '(verify-manual (quote ref))'
                ),
                "helper.pltg": '(fact val 42 :origin "t")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)


class TestConsistency(_TmpDirTestCase):
    """Consistency: diffs that diverge vs converge."""

    def test_consistent_diff(self):
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": (
                    '(import (quote a))\n'
                    '(fact expected 10 :origin "t")\n'
                    '(diff check :replace expected :with a.actual)'
                ),
                "a.pltg": '(fact actual 10 :origin "t")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)

    def test_divergent_diff(self):
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": (
                    '(import (quote a))\n'
                    '(fact expected 10 :origin "t")\n'
                    '(diff check :replace expected :with a.actual)'
                ),
                "a.pltg": '(fact actual 99 :origin "t")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.CONSISTENCY)

    def test_cross_module_diff_both_imported(self):
        """Diff compares facts from two different modules."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": ('(import (quote a))\n' '(import (quote b))\n' '(diff cross :replace a.x :with b.y)'),
                "a.pltg": '(fact x 42 :origin "t")',
                "b.pltg": '(fact y 42 :origin "t")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)


class TestDocumentLoading(_TmpDirTestCase):
    """Document loading and evidence quoting across modules."""

    def test_load_document_in_submodule(self):
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote checker))',
                "checker.pltg": (
                    '(load-document "report" "data.txt")\n'
                    '(fact found true :evidence (evidence "report" :quotes ("hello world")))'
                ),
                "data.txt": 'hello world is here',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)

    def test_ungrounded_quote(self):
        """Quote that doesn't match document text."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote checker))',
                "checker.pltg": (
                    '(load-document "report" "data.txt")\n'
                    '(fact found true :evidence (evidence "report" :quotes ("does not exist")))'
                ),
                "data.txt": 'actual content here',
            },
        )
        # Ungrounded quotes produce consistency warnings, not errors
        result = _classify_lazy(self._main())
        self.assertIn(result.outcome, (Outcome.OK, Outcome.CONSISTENCY))


class TestEffectErrors(_TmpDirTestCase):
    """Effects that fail at runtime."""

    def test_verify_manual_unknown(self):
        """verify-manual on a name that doesn't exist."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(verify-manual (quote nonexistent))',
            },
        )
        # Strict loader raises, lazy loader logs warning
        strict = _classify_strict(self._main())
        self.assertIn(strict.outcome, (Outcome.EFFECT_ERR, Outcome.RESOLVE_ERR))

    def test_load_document_missing_file(self):
        """load-document with nonexistent file."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(load-document "report" "missing.txt")',
            },
        )
        strict = _classify_strict(self._main())
        lazy = _classify_lazy(self._main())
        # Both should report an error (file not found)
        self.assertNotEqual(strict.outcome, Outcome.OK)
        self.assertNotEqual(lazy.outcome, Outcome.OK)


class TestForwardReferences(_TmpDirTestCase):
    """Forward references: diff references name defined later in same file."""

    def test_forward_ref_same_file(self):
        """Strict loader can't resolve forward refs; lazy loader can."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote mod))',
                "mod.pltg": (
                    '(diff d1 :replace later-fact :with early-fact)\n'
                    '(fact early-fact 1 :origin "t")\n'
                    '(fact later-fact 1 :origin "t")'
                ),
            },
        )
        # Lazy loader handles forward refs (parses all then resolves)
        lazy = _classify_lazy(self._main())
        self.assertEqual(lazy.outcome, Outcome.OK)

    def test_forward_ref_in_derive(self):
        """derive using a fact defined later — forward refs fail because
        _patch_symbols only namespaces symbols already registered."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote mod))',
                "mod.pltg": (
                    '(derive early-thm (and later-fact another-fact))\n'
                    '(fact later-fact true :origin "t")\n'
                    '(fact another-fact true :origin "t")'
                ),
            },
        )
        # Forward refs in derive fail: symbols not registered when derive is processed
        lazy = _classify_lazy(self._main())
        self.assertEqual(lazy.outcome, Outcome.EFFECT_ERR)


class TestRunOnEntry(_TmpDirTestCase):
    """run-on-entry only executes in main module."""

    def test_run_on_entry_main(self):
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": ('(run-on-entry (quote (fact entry-ran true :origin "entry")))'),
            },
        )
        lazy = _classify_lazy(self._main())
        self.assertEqual(lazy.outcome, Outcome.OK)
        self.assertIn("entry-ran", lazy.names)

    def test_run_on_entry_submodule_skipped(self):
        """run-on-entry in imported module should NOT execute."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote sub))\n(fact main-fact true :origin "t")',
                "sub.pltg": (
                    '(run-on-entry (quote (fact sub-entry true :origin "entry")))\n' '(fact sub-fact true :origin "t")'
                ),
            },
        )
        lazy = _classify_lazy(self._main())
        self.assertEqual(lazy.outcome, Outcome.OK)
        self.assertIn("sub.sub-fact", lazy.names)
        self.assertNotIn("sub.sub-entry", lazy.names)
        self.assertNotIn("sub-entry", lazy.names)


class TestDiamondImport(_TmpDirTestCase):
    """Diamond import: A imports B and C, both import D."""

    def test_diamond(self):
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote b))\n(import (quote c))',
                "b.pltg": '(import (quote d))\n(fact b-val true :origin "t")',
                "c.pltg": '(import (quote d))\n(fact c-val true :origin "t")',
                "d.pltg": '(fact shared 42 :origin "t")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)
        self._assert_names_present(self._main(), {"d.shared", "b.b-val", "c.c-val"})

    def test_diamond_with_alias(self):
        """Diamond where one path uses dotted import (creates alias)."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote b))\n(import (quote c))',
                "b.pltg": '(import (quote pkg.d))\n(fact b-val true :origin "t")',
                "c.pltg": '(import (quote pkg.d))\n(fact c-val true :origin "t")',
                "pkg/d.pltg": '(fact shared 42 :origin "t")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)


class TestContextEffect(_TmpDirTestCase):
    """(context :file) / (context :name) resolve to correct module."""

    def test_context_file(self):
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": ('(import (quote sub))\n' '(fact main-file (context :file) :origin "ctx")'),
                "sub.pltg": '(fact sub-file (context :file) :origin "ctx")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)

    def test_context_name(self):
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": ('(import (quote sub))\n' '(fact main-name (context :name) :origin "ctx")'),
                "sub.pltg": '(fact sub-name (context :name) :origin "ctx")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)


class TestErrorLocations(_TmpDirTestCase):
    """PltgError contains clickable file:// links with line numbers."""

    def test_error_has_file_link(self):
        """PltgError from strict loader includes file:// URI."""
        from parseltongue.core.loader.loader import PltgError, load_pltg

        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote bad))',
                "bad.pltg": '(verify-manual (quote nonexistent))',
            },
        )
        with self.assertRaises(PltgError) as ctx:
            load_pltg(self._main())

        msg = str(ctx.exception)
        self.assertIn("file://", msg)

    def test_error_has_line_number(self):
        """PltgError includes line number."""
        from parseltongue.core.loader.loader import PltgError, load_pltg

        _write_tree(
            self.tmpdir,
            {
                "main.pltg": ('; line 1 comment\n' '; line 2 comment\n' '(import (quote missing_module))'),
            },
        )
        with self.assertRaises(PltgError) as ctx:
            load_pltg(self._main())

        msg = str(ctx.exception)
        self.assertIn("file://", msg)
        # Should have line:col info
        self.assertRegex(msg, r":\d+:\d+")

    def test_lazy_strict_error_has_uri(self):
        """Lazy loader in strict mode includes file:// URI."""
        from parseltongue.core.loader.lazy_loader import lazy_load_pltg

        _write_tree(
            self.tmpdir,
            {
                "main.pltg": '(import (quote missing_module))',
            },
        )
        with self.assertRaises(SystemError) as ctx:
            lazy_load_pltg(self._main(), strict=True)

        msg = str(ctx.exception)
        self.assertIn("file://", msg)


class TestConsistencyErrorLocation(_TmpDirTestCase):
    """Consistency errors point to the right .pltg file and line."""

    def test_consistency_resolve_error_location(self):
        """When consistency fails to resolve a symbol, error points to the diff."""
        from parseltongue.core.loader.loader import PltgError, load_pltg

        _write_tree(
            self.tmpdir,
            {
                "main.pltg": ('(import (quote checker))\n' '(consistency :raise)'),
                "checker.pltg": (
                    '(fact known true :origin "t")\n' '(diff bad-diff :replace nonexistent-symbol :with known)'
                ),
            },
        )
        try:
            load_pltg(self._main())
        except PltgError as e:
            msg = str(e)
            self.assertIn("file://", msg)


class TestMultipleImportPaths(_TmpDirTestCase):
    """Same module reachable via different import paths."""

    def test_reimport_same_file_different_name(self):
        """Importing two different files whose short aliases don't collide."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": (
                    '(import (quote utils))\n'
                    '(import (quote pkg.helpers))\n'
                    '(diff d1 :replace utils.x :with pkg.helpers.y)'
                ),
                "utils.pltg": '(fact x 1 :origin "t")',
                "pkg/helpers.pltg": '(fact y 1 :origin "t")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)

    def test_reimport_exact_same_file(self):
        """Importing exact same file via two paths — second is skipped."""
        _write_tree(
            self.tmpdir,
            {
                "main.pltg": ('(import (quote a))\n' '(import (quote b))'),
                "a.pltg": '(import (quote shared))\n(fact a-val true :origin "t")',
                "b.pltg": '(import (quote shared))\n(fact b-val true :origin "t")',
                "shared.pltg": '(fact s 1 :origin "t")',
            },
        )
        self._assert_loaders_agree(self._main(), Outcome.OK)
        self._assert_names_present(self._main(), {"shared.s", "a.a-val", "b.b-val"})


if __name__ == "__main__":
    unittest.main()
