"""Tests for parseltongue.cli.export_resolver."""

import tempfile
from pathlib import Path

from parseltongue.cli.export_resolver import (
    namespace_refs,
    resolve_export_names,
    tokenize_with_positions,
)

# ---------------------------------------------------------------------------
# tokenize_with_positions
# ---------------------------------------------------------------------------


class TestTokenizeWithPositions:
    def test_simple_expr(self):
        tokens = tokenize_with_positions("(fact a 1)")
        assert tokens == [
            ("(", 0, 1),
            ("fact", 1, 5),
            ("a", 6, 7),
            ("1", 8, 9),
            (")", 9, 10),
        ]

    def test_string_token(self):
        tokens = tokenize_with_positions('(fact a "hello world")')
        assert ("\"hello world\"", 8, 21) in tokens

    def test_comments_skipped(self):
        src = ";; this is a comment\n(fact a 1)"
        tokens = tokenize_with_positions(src)
        token_strs = [t for t, _, _ in tokens]
        assert "this" not in token_strs
        assert "fact" in token_strs

    def test_multiline(self):
        src = "(fact a\n  1)"
        tokens = tokenize_with_positions(src)
        token_strs = [t for t, _, _ in tokens]
        assert token_strs == ["(", "fact", "a", "1", ")"]

    def test_positions_are_correct(self):
        src = "(defterm interest-rate 0.05)"
        tokens = tokenize_with_positions(src)
        for tok, start, end in tokens:
            if tok not in ("(", ")"):
                assert src[start:end] == tok

    def test_escaped_string(self):
        src = r'(fact a "line1\nline2")'
        tokens = tokenize_with_positions(src)
        strings = [t for t, _, _ in tokens if t.startswith('"')]
        assert len(strings) == 1


# ---------------------------------------------------------------------------
# resolve_export_names
# ---------------------------------------------------------------------------


class TestResolveExportNames:
    def test_single_pass_no_cross_refs(self):
        """Single pass — nothing to resolve."""
        source = '(fact revenue 1000)\n(fact cost 500)'
        patched, bare_to_ns = resolve_export_names([("pass1", source)])

        assert patched["pass1"] == source  # no changes
        assert bare_to_ns == {"revenue": "pass1", "cost": "pass1"}

    def test_two_passes_cross_ref(self):
        """pass2 references pass1's definition — should be namespaced."""
        pass1 = '(fact interest-rate 0.05)'
        pass2 = '(fact payment (* interest-rate 1000))'

        patched, bare_to_ns = resolve_export_names(
            [
                ("pass1", pass1),
                ("pass2", pass2),
            ]
        )

        # pass1 unchanged
        assert patched["pass1"] == pass1
        # pass2's reference to interest-rate namespaced
        assert "pass1.interest-rate" in patched["pass2"]
        # definition name NOT namespaced
        assert "(fact payment" in patched["pass2"]
        # import prepended
        assert "(import (quote pass1))" in patched["pass2"]

    def test_definition_name_not_namespaced(self):
        """The name being defined should never be namespaced."""
        pass1 = '(fact base-rate 0.03)'
        pass2 = '(defterm adjusted-rate (+ base-rate 0.01))'

        patched, _ = resolve_export_names(
            [
                ("pass1", pass1),
                ("pass2", pass2),
            ]
        )

        # "adjusted-rate" is pass2's own definition — must stay bare
        assert "(defterm adjusted-rate" in patched["pass2"]
        # "base-rate" is from pass1 — must be namespaced
        assert "pass1.base-rate" in patched["pass2"]

    def test_local_name_not_namespaced(self):
        """If pass2 redefines a name from pass1, pass2's local use stays bare."""
        pass1 = '(fact rate 0.03)'
        pass2 = '(fact rate 0.05)\n(fact payment (* rate 100))'

        patched, bare_to_ns = resolve_export_names(
            [
                ("pass1", pass1),
                ("pass2", pass2),
            ]
        )

        # pass2 defines its own "rate", so its use of "rate" stays bare
        assert "pass1.rate" not in patched["pass2"]
        # latest wins in bare_to_ns
        assert bare_to_ns["rate"] == "pass2"

    def test_three_passes_chain(self):
        """pass3 refs from both pass1 and pass2."""
        pass1 = '(fact a 1)'
        pass2 = '(fact b (+ a 1))'
        pass3 = '(fact c (+ a b))'

        patched, bare_to_ns = resolve_export_names(
            [
                ("pass1", pass1),
                ("pass2", pass2),
                ("pass3", pass3),
            ]
        )

        # pass2 refs pass1.a
        assert "pass1.a" in patched["pass2"]
        # pass3 refs pass1.a and pass2.b
        assert "pass1.a" in patched["pass3"]
        assert "pass2.b" in patched["pass3"]
        # pass3 has imports for both
        assert "(import (quote pass1))" in patched["pass3"]
        assert "(import (quote pass2))" in patched["pass3"]

    def test_preserves_formatting(self):
        """Comments, whitespace, evidence blocks survive."""
        pass1 = '(fact rate 0.05)'
        pass2 = ';; Calculate payment\n' '(fact payment\n' '  (* rate  ;; the rate\n' '     1000))'

        patched, _ = resolve_export_names(
            [
                ("pass1", pass1),
                ("pass2", pass2),
            ]
        )

        # Comments preserved
        assert ";; Calculate payment" in patched["pass2"]
        assert ";; the rate" in patched["pass2"]
        # Whitespace structure preserved (rate replaced but surrounding kept)
        assert "pass1.rate" in patched["pass2"]

    def test_variables_and_keywords_untouched(self):
        """?-vars and :-keywords should never be namespaced."""
        pass1 = '(fact a 1)'
        pass2 = '(axiom rule (=> (and (= ?x a) :key true) (fact result ?x)))'

        patched, _ = resolve_export_names(
            [
                ("pass1", pass1),
                ("pass2", pass2),
            ]
        )

        assert "?x" in patched["pass2"]  # not namespaced
        assert ":key" in patched["pass2"]  # not namespaced
        assert "pass1.a" in patched["pass2"]  # cross-ref namespaced

    def test_head_keyword_not_namespaced(self):
        """fact/defterm/axiom etc. are head keywords, never namespaced."""
        pass1 = '(fact fact-value 1)'
        pass2 = '(fact result fact-value)'

        patched, _ = resolve_export_names(
            [
                ("pass1", pass1),
                ("pass2", pass2),
            ]
        )

        # The keyword "fact" at position 0 stays as-is
        assert "(fact result" in patched["pass2"]
        # The cross-ref is namespaced
        assert "pass1.fact-value" in patched["pass2"]

    def test_hyphenated_names_exact(self):
        """Hyphenated names must be replaced exactly, not partially."""
        pass1 = '(fact conversion-trigger true)\n' '(fact case-immediate-equity-round-conversion-trigger true)'
        pass2 = '(fact result conversion-trigger)'

        patched, _ = resolve_export_names(
            [
                ("pass1", pass1),
                ("pass2", pass2),
            ]
        )

        # Only the exact cross-ref is namespaced
        assert "pass1.conversion-trigger" in patched["pass2"]
        # The longer name in pass1 is untouched
        assert "case-immediate-equity-round-conversion-trigger" in patched["pass1"]
        assert "pass1.case-immediate-equity-round-conversion-trigger" not in patched["pass1"]

    def test_nested_expressions(self):
        """Cross-refs inside nested expressions are found."""
        pass1 = '(fact x 1)\n(fact y 2)'
        pass2 = '(fact z (if (> x 0) (+ x y) 0))'

        patched, _ = resolve_export_names(
            [
                ("pass1", pass1),
                ("pass2", pass2),
            ]
        )

        assert "pass1.x" in patched["pass2"]
        assert "pass1.y" in patched["pass2"]
        # definition name stays bare
        assert "(fact z" in patched["pass2"]

    def test_evidence_blocks_preserved(self):
        """Evidence blocks in source are preserved."""
        pass1 = '(fact rate 0.05)'
        pass2 = '(fact payment (* rate 1000))\n' '(evidence payment\n' '  "Based on standard rate calculation")'

        patched, _ = resolve_export_names(
            [
                ("pass1", pass1),
                ("pass2", pass2),
            ]
        )

        assert "(evidence payment" in patched["pass2"]
        assert "pass1.rate" in patched["pass2"]


# ---------------------------------------------------------------------------
# namespace_refs
# ---------------------------------------------------------------------------


class TestNamespaceRefs:
    def test_basic_ref(self):
        bare_to_ns = {"revenue": "pass1", "cost": "pass2"}
        text = "The [[fact:revenue]] was high."
        result = namespace_refs(text, bare_to_ns)
        assert result == "The [[fact:pass1.revenue]] was high."

    def test_with_prefix(self):
        bare_to_ns = {"revenue": "pass1"}
        text = "See [[fact:revenue]]."
        result = namespace_refs(text, bare_to_ns, prefix="sources.")
        assert result == "See [[fact:sources.pass1.revenue]]."

    def test_unknown_ref_unchanged(self):
        bare_to_ns = {"revenue": "pass1"}
        text = "The [[fact:unknown-name]] stays."
        result = namespace_refs(text, bare_to_ns)
        assert result == text

    def test_multiple_refs(self):
        bare_to_ns = {"a": "pass1", "b": "pass2"}
        text = "[[fact:a]] and [[term:b]]"
        result = namespace_refs(text, bare_to_ns)
        assert result == "[[fact:pass1.a]] and [[term:pass2.b]]"

    def test_no_refs(self):
        result = namespace_refs("no refs here", {"a": "pass1"})
        assert result == "no refs here"

    def test_hyphenated_ref(self):
        bare_to_ns = {"interest-rate": "pass1"}
        text = "[[fact:interest-rate]]"
        result = namespace_refs(text, bare_to_ns)
        assert result == "[[fact:pass1.interest-rate]]"


# ---------------------------------------------------------------------------
# Integration: resolve → write files → load with Loader
# ---------------------------------------------------------------------------


class TestResolveAndLoad:
    """Write resolved pass files to a temp dir and load them with the real Loader."""

    def _write_project(self, tmp: Path, pass_sources: list[tuple[str, str]], output_md: str = "") -> Path:
        """Resolve, write sources + pgmd, return entry path."""
        patched, bare_to_ns_short = resolve_export_names(pass_sources)
        bare_to_ns = {b: f"sources.{m}" for b, m in bare_to_ns_short.items()}

        sources_dir = tmp / "sources"
        sources_dir.mkdir()
        for mod_name, _ in pass_sources:
            (sources_dir / f"{mod_name}.pltg").write_text(patched[mod_name])

        header = ["```scheme", ";; pltg"]
        for mod_name, _ in pass_sources:
            header.append(f"(import (quote sources.{mod_name}))")
        header.append("```")
        header.append("")

        if bare_to_ns and output_md:
            output_md = namespace_refs(output_md, bare_to_ns)

        entry = tmp / "main.pltg"
        # Extract just the pltg code for loading (no markdown)
        pltg_lines = []
        for mod_name, _ in pass_sources:
            pltg_lines.append(f"(import (quote sources.{mod_name}))")
        entry.write_text("\n".join(pltg_lines) + "\n")
        return entry

    def test_two_passes_loader(self):
        """Two passes with cross-refs load successfully."""
        from parseltongue.core.loader import Loader

        pass1 = '(fact interest-rate 0.05)'
        pass2 = '(fact payment (* interest-rate 1000))'

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entry = self._write_project(tmp_path, [("pass1", pass1), ("pass2", pass2)])

            loader = Loader()
            system = loader.load_main(str(entry))

            # Both facts exist in the system under namespaced names
            all_names = {str(k) for k in system.facts}
            assert "sources.pass1.interest-rate" in all_names
            assert "sources.pass2.payment" in all_names

    def test_three_passes_chain_loader(self):
        """Three-pass chain: pass3 uses names from pass1 and pass2."""
        from parseltongue.core.loader import Loader

        pass1 = '(fact a 10)'
        pass2 = '(fact b (+ a 2))'
        pass3 = '(fact c (+ a b))'

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entry = self._write_project(
                tmp_path,
                [
                    ("pass1", pass1),
                    ("pass2", pass2),
                    ("pass3", pass3),
                ],
            )

            loader = Loader()
            system = loader.load_main(str(entry))

            all_names = {str(k) for k in system.facts}
            assert "sources.pass1.a" in all_names
            assert "sources.pass2.b" in all_names
            assert "sources.pass3.c" in all_names

            # Verify cross-refs are correctly namespaced in wff
            b_fact = system.facts[next(k for k in system.facts if str(k) == "sources.pass2.b")]
            c_fact = system.facts[next(k for k in system.facts if str(k) == "sources.pass3.c")]
            # b = (+ a 1) → wff references sources.pass1.a
            b_syms = [str(s) for s in b_fact.wff if hasattr(s, '__str__') and 'pass1' in str(s)]
            assert any("sources.pass1.a" in s for s in b_syms)
            # c = (+ a b) → wff references both sources.pass1.a and sources.pass2.b
            c_strs = [str(s) for s in c_fact.wff if hasattr(s, '__str__')]
            assert any("sources.pass1.a" in s for s in c_strs)
            assert any("sources.pass2.b" in s for s in c_strs)

    def test_local_override_loader(self):
        """pass2 redefines a name — its local version wins."""
        from parseltongue.core.loader import Loader

        pass1 = '(fact rate 0.03)'
        pass2 = '(fact rate 0.05)\n(fact payment (* rate 100))'

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            entry = self._write_project(tmp_path, [("pass1", pass1), ("pass2", pass2)])

            loader = Loader()
            system = loader.load_main(str(entry))

            all_facts = {str(k): v for k, v in system.facts.items()}
            assert all_facts["sources.pass1.rate"].wff == 0.03
            assert all_facts["sources.pass2.rate"].wff == 0.05
            # payment = (* rate 100) — rate should be pass2's local (bare), not pass1's
            payment_wff = all_facts["sources.pass2.payment"].wff
            payment_syms = [str(s) for s in payment_wff if hasattr(s, '__str__')]
            # Should reference sources.pass2.rate (local), NOT sources.pass1.rate
            assert any("sources.pass2.rate" in s for s in payment_syms)
            assert not any("sources.pass1.rate" in s for s in payment_syms)

    def test_pass_files_have_correct_imports(self):
        """Verify the actual .pltg files on disk have correct import syntax."""
        pass1 = '(fact a 1)'
        pass2 = '(fact b (+ a 1))'
        pass3 = '(fact c (+ a b))'

        patched, _ = resolve_export_names(
            [
                ("pass1", pass1),
                ("pass2", pass2),
                ("pass3", pass3),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            sources_dir = tmp_path / "sources"
            sources_dir.mkdir()
            for name in ["pass1", "pass2", "pass3"]:
                (sources_dir / f"{name}.pltg").write_text(patched[name])

            # pass1 has no imports
            p1 = (sources_dir / "pass1.pltg").read_text()
            assert "(import" not in p1

            # pass2 imports pass1 (sibling name)
            p2 = (sources_dir / "pass2.pltg").read_text()
            assert "(import (quote pass1))" in p2
            assert "sources." not in p2  # no sources. prefix in sibling imports

            # pass3 imports both pass1 and pass2
            p3 = (sources_dir / "pass3.pltg").read_text()
            assert "(import (quote pass1))" in p3
            assert "(import (quote pass2))" in p3

    def test_pgmd_refs_namespaced(self):
        """Markdown refs get full sources.passN.name namespacing."""
        pass1 = '(fact revenue 1000)'
        pass2 = '(fact cost 500)'
        output_md = "Revenue is [[fact:revenue]] and cost is [[fact:cost]]."

        _, bare_to_ns_short = resolve_export_names(
            [
                ("pass1", pass1),
                ("pass2", pass2),
            ]
        )
        bare_to_ns = {b: f"sources.{m}" for b, m in bare_to_ns_short.items()}
        result = namespace_refs(output_md, bare_to_ns)

        assert "[[fact:sources.pass1.revenue]]" in result
        assert "[[fact:sources.pass2.cost]]" in result
