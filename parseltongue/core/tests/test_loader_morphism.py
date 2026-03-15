"""Tests for LoaderMorphismV2 — file-aware namespace patching via NavList."""

from parseltongue.core.ast import AnnotatedDirective, DirectiveKind, NavList
from parseltongue.core.atoms import Symbol
from parseltongue.core.loader.loader_morphism import (
    LoaderAnnotatedDirective,
    ModuleSource,
    MorphismReport,
    PatchContext,
    _lm_v2,
)
from parseltongue.core.loader.loader_morphism import (
    patch_context as _patch_context,
)
from parseltongue.core.loader.loader_morphism import (
    patch_definition_name as _patch_definition_name,
)
from parseltongue.core.loader.loader_morphism import (
    patch_symbols as _patch_symbols,
)

# ============================================================
# Helpers
# ============================================================


def _transform(source, *, source_file="", module_name="", is_main=True):
    """Shortcut: transform source via V2 morphism."""
    ms = ModuleSource(source=source, source_file=source_file, module_name=module_name, is_main=is_main)
    return _lm_v2.transform(ms)


def _transform_and_patch(
    source,
    *,
    source_file="",
    module_name="",
    is_main=True,
    known_names=None,
    module_aliases=None,
    names_to_modules=None,
    names_to_lines=None,
    report=None,
):
    """Transform + apply patching (replicates V1 behavior for tests)."""
    lads = _transform(source, source_file=source_file, module_name=module_name, is_main=is_main)
    n2l = names_to_lines if names_to_lines is not None else {}

    ctx = PatchContext(
        module_name=module_name,
        source_file=source_file,
        known_names=known_names or set(),
        aliases=module_aliases or {},
        names_to_modules=names_to_modules if names_to_modules is not None else {},
        report=report,
    )

    for lad in lads:
        ad = lad.directive
        expr = ad.sentence.expr

        # Namespace definition names for non-main modules
        if lad.needs_namespace:
            _patch_definition_name(ad, ctx)

        # Track name → line
        if ad.node.name:
            n2l[ad.node.name] = ad.sentence.line

        # Patch context keys
        _patch_context(expr, ctx, ad.sentence.line)

        # Patch symbols to namespaced versions
        if known_names is not None:
            if not is_main:
                _patch_symbols(expr, ctx, ad.sentence.line, skip_index=lad.skip_index)
            elif ctx.aliases:
                _patch_symbols(expr, ctx, ad.sentence.line)

    return [lad.directive for lad in lads]


def names(directives: list[AnnotatedDirective]) -> list[str | None]:
    return [ad.node.name for ad in directives]


def symbol_at(ad: AnnotatedDirective, *path: int):
    """Navigate into expr by indices, return the value."""
    v = ad.sentence.expr
    for i in path:
        v = v[i]
    return v


# ============================================================
# V2 morphism — pure analysis (no patching)
# ============================================================


class TestV2Analysis:
    def test_returns_loader_annotated_directives(self):
        source = '(fact x 42 :origin "test")'
        lads = _transform(source)
        assert len(lads) == 1
        assert isinstance(lads[0], LoaderAnnotatedDirective)

    def test_tags_source_file(self):
        source = '(fact x 42 :origin "test")'
        lads = _transform(source, source_file="main.pltg")
        assert lads[0].source_file == "main.pltg"
        assert lads[0].directive.node.source_file == "main.pltg"

    def test_detects_definition(self):
        source = '(fact x 42)\n(some-effect args)'
        lads = _transform(source)
        assert lads[0].is_definition is True
        assert lads[1].is_definition is False

    def test_needs_namespace_only_non_main(self):
        lads_main = _transform("(fact x 42)", is_main=True)
        lads_mod = _transform("(fact x 42)", module_name="m", is_main=False)
        assert lads_main[0].needs_namespace is False
        assert lads_mod[0].needs_namespace is True

    def test_skip_index(self):
        lads = _transform("(fact x 42)", module_name="m", is_main=False)
        assert lads[0].skip_index == 1  # name position

    def test_carries_module_context(self):
        lads = _transform("(fact x 42)", source_file="a.pltg", module_name="m", is_main=False)
        assert lads[0].module_name == "m"
        assert lads[0].is_main is False


# ============================================================
# Basic transform — no namespacing (main module)
# ============================================================


class TestMainModule:
    def test_main_preserves_names(self):
        source = '(fact x 42 :origin "test")\n(fact y true :origin "test")'
        ds = _transform_and_patch(source, is_main=True)
        assert names(ds) == ["x", "y"]

    def test_main_tags_source_file(self):
        source = '(fact x 42 :origin "test")'
        ds = _transform_and_patch(source, source_file="main.pltg", is_main=True)
        assert ds[0].node.source_file == "main.pltg"

    def test_main_tracks_lines(self):
        source = '(fact x 1)\n\n(fact y 2)'
        ds = _transform_and_patch(source, is_main=True)
        assert ds[0].sentence.line == 1
        assert ds[1].sentence.line == 3

    def test_main_no_symbol_patching_without_known_names(self):
        source = '(defterm y (+ x 1))'
        ds = _transform_and_patch(source, is_main=True)
        assert symbol_at(ds[0], 2, 1) == Symbol("x")

    def test_main_resolves_aliases(self):
        source = '(defterm y (+ utils.x 1))'
        ds = _transform_and_patch(
            source,
            is_main=True,
            module_name="main",
            known_names={"std.utils.x"},
            module_aliases={"utils": "std.utils"},
        )
        assert symbol_at(ds[0], 2, 1) == Symbol("std.utils.x")


# ============================================================
# Non-main module — definition namespacing
# ============================================================


class TestNonMainModule:
    def test_namespaces_fact(self):
        source = '(fact x 42 :origin "test")'
        ds = _transform_and_patch(source, module_name="m", is_main=False)
        assert ds[0].node.name == "m.x"
        assert str(ds[0].sentence.expr[1]) == "m.x"

    def test_namespaces_defterm(self):
        source = "(defterm y (+ x 1))"
        ds = _transform_and_patch(source, module_name="pkg.mod", is_main=False)
        assert ds[0].node.name == "pkg.mod.y"

    def test_namespaces_derive(self):
        source = '(derive thm (= a b) :using (x y))'
        ds = _transform_and_patch(source, module_name="m", is_main=False)
        assert ds[0].node.name == "m.thm"

    def test_namespaces_axiom(self):
        source = '(axiom rule (implies ?x ?y) :origin "test")'
        ds = _transform_and_patch(source, module_name="m", is_main=False)
        assert ds[0].node.name == "m.rule"

    def test_namespaces_diff(self):
        source = "(diff d :replace a :with b)"
        ds = _transform_and_patch(source, module_name="m", is_main=False)
        assert ds[0].node.name == "m.d"

    def test_names_to_modules_populated(self):
        source = "(fact x 1)\n(fact y 2)"
        n2m = {}
        _transform_and_patch(source, module_name="m", is_main=False, names_to_modules=n2m)
        assert n2m == {"m.x": "m", "m.y": "m"}

    def test_names_to_lines_populated(self):
        source = "(fact x 1)\n(fact y 2)"
        n2l = {}
        _transform_and_patch(source, module_name="m", is_main=False, names_to_lines=n2l)
        assert n2l == {"m.x": 1, "m.y": 2}


# ============================================================
# Symbol patching
# ============================================================


class TestSymbolPatching:
    def test_patches_known_symbol_in_body(self):
        source = "(defterm y (+ x 1))"
        ds = _transform_and_patch(
            source,
            module_name="m",
            is_main=False,
            known_names={"m.x"},
        )
        body = ds[0].sentence.expr[2]
        assert body[1] == Symbol("m.x")

    def test_skips_definition_name_in_patching(self):
        """The name at index 1 shouldn't be double-namespaced."""
        source = "(fact x 42)"
        ds = _transform_and_patch(
            source,
            module_name="m",
            is_main=False,
            known_names={"m.x"},
        )
        assert ds[0].node.name == "m.x"

    def test_patches_using_list(self):
        source = "(derive thm (= a b) :using (x y))"
        ds = _transform_and_patch(
            source,
            module_name="m",
            is_main=False,
            known_names={"m.x", "m.y"},
        )
        using = ds[0].sentence.expr[4]
        assert Symbol("m.x") in using
        assert Symbol("m.y") in using

    def test_leaves_unknown_symbols_bare(self):
        source = "(defterm y (+ x unknown))"
        ds = _transform_and_patch(
            source,
            module_name="m",
            is_main=False,
            known_names={"m.x"},
        )
        body = ds[0].sentence.expr[2]
        assert body[1] == Symbol("m.x")
        assert body[2] == Symbol("unknown")

    def test_resolves_module_aliases(self):
        source = "(defterm y (+ utils.x 1))"
        ds = _transform_and_patch(
            source,
            module_name="m",
            is_main=False,
            known_names={"std.utils.x"},
            module_aliases={"utils": "std.utils"},
        )
        body = ds[0].sentence.expr[2]
        assert body[1] == Symbol("std.utils.x")

    def test_ignores_keyword_args(self):
        source = '(fact x 42 :origin "test")'
        ds = _transform_and_patch(source, module_name="m", is_main=False, known_names={"m.:origin"})
        assert ds[0].sentence.expr[3] == ":origin"

    def test_ignores_variable_symbols(self):
        source = "(axiom rule (implies ?x ?y))"
        ds = _transform_and_patch(source, module_name="m", is_main=False, known_names={"m.?x"})
        body = ds[0].sentence.expr[2]
        assert body[1] == Symbol("?x")


# ============================================================
# Std library resolution
# ============================================================


class TestStdResolution:
    def test_unimported_std_via_full_path(self):
        """std.counting.count resolves via alias std.counting → std.counting."""
        source = "(defterm x (+ std.counting.count 1))"
        ds = _transform_and_patch(
            source,
            module_name="main",
            is_main=True,
            known_names={"std.counting.count"},
            module_aliases={"std.counting": "std.counting"},
        )
        assert symbol_at(ds[0], 2, 1) == Symbol("std.counting.count")

    def test_imported_std_bare_name(self):
        """After importing std.counting, bare 'count' resolves to std.counting.count."""
        source = "(defterm x (+ count 1))"
        ds = _transform_and_patch(
            source,
            module_name="main",
            is_main=True,
            known_names={"std.counting.count"},
            module_aliases={"counting": "std.counting"},
        )
        assert symbol_at(ds[0], 2, 1) == Symbol("std.counting.count")

    def test_imported_std_short_alias(self):
        """Short alias: 'import std.counting as c' → c.count resolves."""
        source = "(defterm x (+ c.count 1))"
        ds = _transform_and_patch(
            source,
            module_name="main",
            is_main=True,
            known_names={"std.counting.count"},
            module_aliases={"c": "std.counting"},
        )
        assert symbol_at(ds[0], 2, 1) == Symbol("std.counting.count")

    def test_multiple_std_imports(self):
        """Multiple std libs imported — each resolves independently."""
        source = "(defterm x (+ count total))"
        ds = _transform_and_patch(
            source,
            module_name="main",
            is_main=True,
            known_names={"std.counting.count", "std.math.total"},
            module_aliases={"counting": "std.counting", "math": "std.math"},
        )
        body = ds[0].sentence.expr[2]
        assert body[1] == Symbol("std.counting.count")
        assert body[2] == Symbol("std.math.total")

    def test_std_in_non_main_module(self):
        """Non-main module can also resolve std references."""
        source = "(defterm y (+ count 1))"
        ds = _transform_and_patch(
            source,
            module_name="mymod",
            is_main=False,
            known_names={"std.counting.count"},
            module_aliases={"counting": "std.counting"},
        )
        body = ds[0].sentence.expr[2]
        assert body[1] == Symbol("std.counting.count")

    def test_std_dotted_unresolved_warns(self):
        """Dotted symbol that doesn't resolve should produce a warning."""
        report = MorphismReport()
        source = "(defterm x (+ nonexistent.thing 1))"
        ds = _transform_and_patch(
            source,
            module_name="m",
            is_main=False,
            known_names=set(),
            report=report,
        )
        assert report.has_warnings
        assert any("nonexistent.thing" in w.symbol for w in report.warnings)

    def test_std_priority_module_over_alias(self):
        """Module-local name takes priority over alias resolution."""
        source = "(defterm x (+ count 1))"
        ds = _transform_and_patch(
            source,
            module_name="m",
            is_main=False,
            known_names={"m.count", "std.counting.count"},
            module_aliases={"counting": "std.counting"},
        )
        # m.count wins over std.counting.count
        body = ds[0].sentence.expr[2]
        assert body[1] == Symbol("m.count")


# ============================================================
# Reporting
# ============================================================


class TestReporting:
    def test_report_collects_resolutions(self):
        report = MorphismReport()
        source = "(defterm y (+ x 1))"
        _transform_and_patch(
            source,
            module_name="m",
            is_main=False,
            known_names={"m.x"},
            report=report,
        )
        assert len(report.resolutions) > 0
        # Should have definition resolution for y and module resolution for x
        defs = [r for r in report.resolutions if r.via == "definition"]
        mods = [r for r in report.resolutions if r.via == "module"]
        assert len(defs) == 1
        assert defs[0].original == "y"
        assert defs[0].resolved == "m.y"
        assert len(mods) == 1
        assert mods[0].original == "x"
        assert mods[0].resolved == "m.x"

    def test_report_collects_alias_resolutions(self):
        report = MorphismReport()
        source = "(defterm y (+ utils.x 1))"
        _transform_and_patch(
            source,
            module_name="m",
            is_main=False,
            known_names={"std.utils.x"},
            module_aliases={"utils": "std.utils"},
            report=report,
        )
        alias_res = [r for r in report.resolutions if "alias" in r.via]
        assert len(alias_res) == 1
        assert alias_res[0].original == "utils.x"
        assert alias_res[0].resolved == "std.utils.x"

    def test_report_warns_on_unresolved_dotted(self):
        report = MorphismReport()
        source = "(defterm y (+ bad.ref 1))"
        _transform_and_patch(
            source,
            module_name="m",
            is_main=False,
            known_names=set(),
            report=report,
        )
        assert report.has_warnings
        assert report.warnings[0].symbol == "bad.ref"

    def test_report_no_warnings_on_clean_input(self):
        report = MorphismReport()
        source = "(fact x 42)"
        _transform_and_patch(
            source,
            module_name="m",
            is_main=False,
            report=report,
        )
        assert not report.has_warnings

    def test_report_tracks_file_and_line(self):
        report = MorphismReport()
        source = "(fact x 1)\n(defterm y (+ x 1))"
        _transform_and_patch(
            source,
            source_file="test.pltg",
            module_name="m",
            is_main=False,
            known_names={"m.x"},
            report=report,
        )
        for r in report.resolutions:
            assert r.file == "test.pltg"
        # x resolution should be on line 2
        mod_res = [r for r in report.resolutions if r.via == "module"]
        assert mod_res[0].line == 2

    def test_report_context_resolution(self):
        report = MorphismReport()
        source = "(context :file)"
        _transform_and_patch(
            source,
            module_name="m",
            is_main=False,
            names_to_modules={},
            report=report,
        )
        ctx_res = [r for r in report.resolutions if r.via == "context"]
        assert len(ctx_res) == 1


# ============================================================
# Context patching
# ============================================================


class TestContextPatching:
    def test_patches_context_key(self):
        source = "(context :file)"
        n2m = {}
        ds = _transform_and_patch(source, module_name="m", is_main=False, names_to_modules=n2m)
        assert ds[0].sentence.expr[1] == "m.:file"
        assert n2m["m.:file"] == "m"

    def test_patches_nested_context(self):
        source = "(fact x (context :key))"
        n2m = {}
        ds = _transform_and_patch(source, module_name="m", is_main=False, names_to_modules=n2m)
        assert "m.:key" in n2m


# ============================================================
# NavList parent refs
# ============================================================


class TestNavListParentRefs:
    def test_expr_is_navlist(self):
        source = "(fact x 42)"
        ds = _transform_and_patch(source, is_main=True)
        assert isinstance(ds[0].sentence.expr, NavList)

    def test_nested_lists_are_navlists(self):
        source = "(defterm y (+ x 1))"
        ds = _transform_and_patch(source, is_main=True)
        body = ds[0].sentence.expr[2]
        assert isinstance(body, NavList)

    def test_parent_ref_points_to_expr(self):
        source = "(defterm y (+ x 1))"
        ds = _transform_and_patch(source, is_main=True)
        body = ds[0].sentence.expr[2]
        assert body.parent is ds[0].sentence.expr
        assert body.pos == 2

    def test_patch_via_parent_ref(self):
        source = "(defterm y (+ x 1))"
        ds = _transform_and_patch(source, is_main=True)
        body = ds[0].sentence.expr[2]
        body.parent[body.pos] = [Symbol("*"), Symbol("x"), 2]
        assert ds[0].sentence.expr[2] == [Symbol("*"), Symbol("x"), 2]

    def test_deeply_nested_parent_chain(self):
        source = "(defterm y (if (= x 1) (+ x 2) 0))"
        ds = _transform_and_patch(source, is_main=True)
        body = ds[0].sentence.expr[2]
        cond = body[1]
        assert isinstance(cond, NavList)
        assert cond.parent is body
        assert cond.pos == 1
        assert cond.parent.parent is ds[0].sentence.expr


# ============================================================
# Structural index
# ============================================================


class TestStructuralIndex:
    def test_fact_index(self):
        source = '(fact x 42 :origin "test")'
        ds = _transform_and_patch(source, is_main=True)
        idx = ds[0].sentence.index
        assert idx.head == 0
        assert idx.name == 1
        assert idx.body == 2
        assert idx.keywords[":origin"] == 4

    def test_derive_index_multiple_keywords(self):
        source = "(derive thm (= x y) :using (a b) :bind z)"
        ds = _transform_and_patch(source, is_main=True)
        idx = ds[0].sentence.index
        assert idx.body == 2
        assert idx.keywords[":using"] == 4
        assert idx.keywords[":bind"] == 6

    def test_no_body_directive(self):
        source = "(diff d :replace a :with b)"
        ds = _transform_and_patch(source, is_main=True)
        idx = ds[0].sentence.index
        assert idx.name == 1
        assert idx.body is None
        assert ":replace" in idx.keywords
        assert ":with" in idx.keywords


# ============================================================
# Directive kinds
# ============================================================


class TestDirectiveKinds:
    def test_all_kinds(self):
        source = """(fact x 1)
(axiom rule (implies ?a ?b))
(defterm y 2)
(derive thm (= x y) :using (x))
(diff d :replace x :with y)
(some-effect args)"""
        ds = _transform_and_patch(source, is_main=True)
        kinds = [ad.node.kind for ad in ds]
        assert kinds == [
            DirectiveKind.FACT,
            DirectiveKind.AXIOM,
            DirectiveKind.DEFTERM,
            DirectiveKind.DERIVE,
            DirectiveKind.DIFF,
            DirectiveKind.EFFECT,
        ]


# ============================================================
# Inverse round-trip
# ============================================================


class TestInverse:
    def test_inverse_produces_valid_sexp(self):
        source = '(fact x 42 :origin "test")\n(defterm y (+ x 1))'
        lads = _transform(source, is_main=True)
        result = _lm_v2.inverse(lads)
        assert "(fact x 42" in result
        assert "(defterm y (+ x 1))" in result

    def test_inverse_uses_original_wff(self):
        """Patching expr should NOT affect inverse (uses frozen wff)."""
        source = "(defterm y (+ x 1))"
        ds = _transform_and_patch(source, is_main=True)
        ds[0].sentence.expr[2] = [Symbol("*"), Symbol("z"), 99]
        lads = _transform(source, is_main=True)
        result = _lm_v2.inverse(lads)
        assert "(+ x 1)" in result
        assert "z" not in result


# ============================================================
# Multi-file scenarios with temp files
# ============================================================


class TestMultiFile:
    def test_two_modules_no_collision(self, tmp_path):
        """Two modules define 'x' — namespacing keeps them separate."""
        mod_a = '(fact x 1 :origin "a")\n(defterm y (+ x 1))'
        mod_b = '(fact x 2 :origin "b")\n(defterm z (+ x 1))'

        path_a = str(tmp_path / "a.pltg")
        path_b = str(tmp_path / "b.pltg")
        (tmp_path / "a.pltg").write_text(mod_a)
        (tmp_path / "b.pltg").write_text(mod_b)

        n2m = {}
        ds_a = _transform_and_patch(
            mod_a,
            source_file=path_a,
            module_name="a",
            is_main=False,
            known_names=set(),
            names_to_modules=n2m,
        )
        known = {"a.x"}
        ds_b = _transform_and_patch(
            mod_b,
            source_file=path_b,
            module_name="b",
            is_main=False,
            known_names=known,
            names_to_modules=n2m,
        )

        assert ds_a[0].node.name == "a.x"
        assert ds_b[0].node.name == "b.x"
        assert ds_a[0].node.source_file == path_a
        assert ds_b[0].node.source_file == path_b

    def test_cross_module_alias_resolution(self, tmp_path):
        """Module B references A's definitions via alias."""
        mod_a = "(fact count 5)\n(defterm total (+ count 1))"
        mod_b = "(defterm result (+ a.count a.total))"

        n2m = {}
        known = set()

        ds_a = _transform_and_patch(
            mod_a,
            source_file="a.pltg",
            module_name="pkg.a",
            is_main=False,
            known_names=known,
            names_to_modules=n2m,
        )
        known.update(ad.node.name for ad in ds_a if ad.node.name)

        ds_b = _transform_and_patch(
            mod_b,
            source_file="b.pltg",
            module_name="pkg.b",
            is_main=False,
            known_names=known,
            names_to_modules=n2m,
            module_aliases={"a": "pkg.a"},
        )

        body_b = ds_b[0].sentence.expr[2]
        assert body_b[1] == Symbol("pkg.a.count")
        assert body_b[2] == Symbol("pkg.a.total")

    def test_main_plus_imported_module(self, tmp_path):
        """Main module uses unnamespaced names; imported module is namespaced."""
        main_src = "(fact x 1)\n(defterm y (+ x 1))"
        lib_src = "(fact helper 10)\n(defterm util (+ helper x))"

        n2m = {}
        known = set()

        ds_main = _transform_and_patch(
            main_src,
            source_file="main.pltg",
            module_name="main",
            is_main=True,
            names_to_modules=n2m,
        )
        known.update(ad.node.name for ad in ds_main if ad.node.name)

        ds_lib = _transform_and_patch(
            lib_src,
            source_file="lib.pltg",
            module_name="lib",
            is_main=False,
            known_names=known,
            names_to_modules=n2m,
        )

        assert ds_main[0].node.name == "x"
        assert ds_lib[0].node.name == "lib.helper"

    def test_multiple_files_provenance(self, tmp_path):
        """Each directive tracks back to its source file and line."""
        files = {
            "a.pltg": "(fact a1 1)\n(fact a2 2)\n(fact a3 3)",
            "b.pltg": "(fact b1 10)\n\n\n(fact b2 20)",
        }
        all_directives = []
        for name, content in files.items():
            path = str(tmp_path / name)
            (tmp_path / name).write_text(content)
            ds = _transform_and_patch(
                content,
                source_file=path,
                module_name=name.split(".")[0],
                is_main=False,
            )
            all_directives.extend(ds)

        assert all_directives[0].node.source_file.endswith("a.pltg")
        assert all_directives[0].sentence.line == 1
        assert all_directives[2].sentence.line == 3
        assert all_directives[3].node.source_file.endswith("b.pltg")
        assert all_directives[3].sentence.line == 1
        assert all_directives[4].sentence.line == 4

    def test_incremental_known_names(self, tmp_path):
        """Simulates loader processing files sequentially, growing known_names."""
        sources = [
            ("base.pltg", "base", "(fact x 1)\n(fact y 2)"),
            ("mid.pltg", "mid", "(defterm sum (+ x y))"),
            ("top.pltg", "top", "(derive result (= sum 3) :using (sum))"),
        ]

        known = set()
        n2m = {}
        all_ds = []

        for filename, mod, src in sources:
            ds = _transform_and_patch(
                src,
                source_file=filename,
                module_name=mod,
                is_main=False,
                known_names=known,
                names_to_modules=n2m,
            )
            known.update(ad.node.name for ad in ds if ad.node.name)
            all_ds.extend(ds)

        assert all_ds[0].node.name == "base.x"
        assert all_ds[1].node.name == "base.y"
        # mid's x stays bare — mid.x not in known_names, only base.x is
        mid_body = all_ds[2].sentence.expr[2]
        assert mid_body[1] == Symbol("x")

    def test_incremental_with_aliases(self, tmp_path):
        """Cross-module resolution via aliases in incremental loading."""
        sources = [
            ("base.pltg", "base", "(fact x 1)\n(fact y 2)"),
            ("mid.pltg", "mid", "(defterm sum (+ base.x base.y))"),
        ]

        known = set()
        n2m = {}
        all_ds = []

        for filename, mod, src in sources:
            ds = _transform_and_patch(
                src,
                source_file=filename,
                module_name=mod,
                is_main=False,
                known_names=known,
                names_to_modules=n2m,
                module_aliases={"base": "base"},
            )
            known.update(ad.node.name for ad in ds if ad.node.name)
            all_ds.extend(ds)

        # mid's body resolves base.x → base.x via alias
        mid_body = all_ds[2].sentence.expr[2]
        assert mid_body[1] == Symbol("base.x")
        assert mid_body[2] == Symbol("base.y")

    def test_read_from_temp_files(self, tmp_path):
        """Full round-trip: write files, read them, transform, verify."""
        (tmp_path / "math.pltg").write_text('(fact pi 3.14 :origin "constant")\n' "(defterm tau (* pi 2))\n")
        (tmp_path / "physics.pltg").write_text(
            '(fact c 299792458 :origin "speed of light")\n' "(defterm energy (* c c))\n"
        )

        n2m = {}
        results = {}
        for name in ["math", "physics"]:
            path = tmp_path / f"{name}.pltg"
            content = path.read_text()
            ds = _transform_and_patch(
                content,
                source_file=str(path),
                module_name=f"std.{name}",
                is_main=False,
                names_to_modules=n2m,
            )
            results[name] = ds

        assert results["math"][0].node.name == "std.math.pi"
        assert results["physics"][0].node.name == "std.physics.c"
        assert results["math"][0].node.source_file.endswith("math.pltg")
        assert results["physics"][1].node.source_file.endswith("physics.pltg")

        tau = results["math"][1]
        assert tau.sentence.index.body == 2
        assert tau.sentence.expr[0] == Symbol("defterm")
