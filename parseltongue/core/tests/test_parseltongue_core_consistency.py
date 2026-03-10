"""Self-validation: load core.pltg and check consistency."""

import os
import unittest
from copy import deepcopy

from ..loader import Loader, load_pltg

CORE_PLTG = os.path.join(os.path.dirname(__file__), "..", "validation", "core.pltg")


class TestParseltongueCoreConsistency(unittest.TestCase):

    @classmethod
    def setUpClass(cls):

        loader = Loader()
        cls.system = loader.load_main(CORE_PLTG)
        cls.module_files = {name: ctx.current_file for name, ctx in loader.modules_contexts.items()}

    def test_core_consistency(self):
        report = self.system.consistency()
        print(report.verbose())
        self.assertTrue(report.consistent, f"System inconsistent: {report}")

    def test_all_theorems_evaluate_true(self):
        engine = self.system.engine
        for name, thm in engine.theorems.items():
            result = engine.evaluate(thm.wff)
            self.assertTrue(result, f"Theorem '{name}' evaluated to {result}, expected True")

    def test_no_dangling_definitions_overall(self):
        engine = self.system.engine

        from parseltongue.core.atoms import Symbol

        def _collect_symbols(expr):
            if isinstance(expr, Symbol):
                return {str(expr)}
            if isinstance(expr, list):
                result = set()
                for item in expr:
                    result |= _collect_symbols(item)
                return result
            return set()

        def _follow_terms(name, visited):
            """Recursively follow term definitions to collect all referenced symbols."""
            if name in visited:
                return
            visited.add(name)
            if name in engine.terms:
                term = engine.terms[name]
                if term.definition is not None:
                    for sym in _collect_symbols(term.definition):
                        _follow_terms(sym, visited)

        # Track references by category, following through term definitions
        referenced_by_derives = set()
        for thm in engine.theorems.values():
            for dep in thm.derivation:
                _follow_terms(dep, referenced_by_derives)

        referenced_by_diffs = set()
        for params in engine.diffs.values():
            _follow_terms(params["replace"], referenced_by_diffs)
            _follow_terms(params["with"], referenced_by_diffs)

        referenced = referenced_by_derives | referenced_by_diffs

        # Rewrite-rule axioms: axioms whose WFF references a symbol
        # that is already referenced are themselves in use — the
        # engine applies them automatically during evaluation.
        referenced_by_rewrites = set()
        for ax_name, ax in engine.axioms.items():
            if ax_name in referenced:
                continue
            ax_symbols = _collect_symbols(ax.wff)
            if ax_symbols & referenced:
                referenced_by_rewrites.add(ax_name)
        referenced = referenced | referenced_by_rewrites

        all_facts = set(engine.facts.keys())
        all_axioms = set(engine.axioms.keys())
        all_terms = set(engine.terms.keys())
        all_theorems = set(engine.theorems.keys())
        all_definitions = all_facts | all_axioms | all_terms

        dangling = all_definitions - referenced

        dangling_facts = dangling & all_facts
        dangling_axioms = dangling & all_axioms
        dangling_terms = dangling & all_terms

        print(f"\n{'='*60}")
        print("  Definition Coverage Report")
        print(f"{'='*60}")
        print(f"  Total definitions: {len(all_definitions)}")
        print(f"    Facts: {len(all_facts)}")
        print(f"    Axioms: {len(all_axioms)}")
        print(f"    Terms: {len(all_terms)}")
        print(f"    Theorems: {len(all_theorems)}")
        print(f"  Total diffs: {len(engine.diffs)}")
        print("")
        print(f"  Reachable from derives: {len(all_definitions & referenced_by_derives)}")
        print(f"  Reachable from diffs: {len(all_definitions & referenced_by_diffs)}")
        print(f"  Reachable via rewrites: {len(referenced_by_rewrites)}")
        print(f"  Total reachable: {len(all_definitions & referenced)} / {len(all_definitions)}")
        print(f"  Coverage: {100 * len(all_definitions & referenced) / len(all_definitions):.1f}%")
        print("")
        print(f"  Dangling: {len(dangling)}")
        print(f"    Facts: {len(dangling_facts)}")
        print(f"    Axioms: {len(dangling_axioms)}")
        print(f"    Terms: {len(dangling_terms)}")
        if dangling_facts:
            print("\n  Dangling facts:")
            for name in sorted(dangling_facts):
                print(f"    - {name}")
        if dangling_axioms:
            print("\n  Dangling axioms:")
            for name in sorted(dangling_axioms):
                print(f"    - {name}")
        if dangling_terms:
            print("\n  Dangling terms:")
            for name in sorted(dangling_terms):
                print(f"    - {name}")
        print(f"{'='*60}")

        self.assertEqual(
            dangling, set(), f"Dangling definitions: {len(dangling)} not used in any diff, theorem or term"
        )

    def test_no_dangling_definitions_diffs(self):
        """Every definition must be reachable from a diff via recursive traversal.

        Diffs reference two branches (terms/theorems/facts). Those branches
        reference other definitions via term bodies and theorem derivation
        lists. This test follows the full tree to ensure every fact, axiom,
        term, and theorem is reachable from at least one diff.
        """
        engine = self.system.engine

        from parseltongue.core.atoms import Symbol

        def _collect_symbols(expr):
            if isinstance(expr, Symbol):
                return {str(expr)}
            if isinstance(expr, list):
                result = set()
                for item in expr:
                    result |= _collect_symbols(item)
                return result
            return set()

        # Recursively collect all definitions reachable from a name
        def _reachable(name, visited=None):
            if visited is None:
                visited = set()
            if name in visited:
                return visited
            visited.add(name)

            # If it's a theorem, follow its derivation list
            if name in engine.theorems:
                for dep in engine.theorems[name].derivation:
                    _reachable(dep, visited)

            # If it's a term with a definition, follow symbols in the body
            if name in engine.terms:
                term = engine.terms[name]
                if term.definition is not None:
                    for sym in _collect_symbols(term.definition):
                        if sym in engine.facts or sym in engine.terms or sym in engine.theorems or sym in engine.axioms:
                            _reachable(sym, visited)

            # If it's an axiom, follow symbols in its WFF (rewrite rules
            # reference the terms they rewrite for)
            if name in engine.axioms:
                for sym in _collect_symbols(engine.axioms[name].wff):
                    if sym in engine.facts or sym in engine.terms or sym in engine.theorems or sym in engine.axioms:
                        _reachable(sym, visited)

            # If it's a diff, follow replace and with
            if name in engine.diffs:
                params = engine.diffs[name]
                _reachable(params["replace"], visited)
                _reachable(params["with"], visited)

            return visited

        # Start from all diffs and collect everything reachable
        reachable = set()
        for diff_name in engine.diffs:
            params = engine.diffs[diff_name]
            reachable.add(diff_name)
            _reachable(params["replace"], reachable)
            _reachable(params["with"], reachable)

        # Rewrite-rule axioms: axioms whose WFF references a reachable
        # symbol are themselves in use (the engine applies them automatically)
        for ax_name, ax in engine.axioms.items():
            if ax_name not in reachable:
                ax_symbols = _collect_symbols(ax.wff)
                if ax_symbols & reachable:
                    _reachable(ax_name, reachable)

        all_facts = set(engine.facts.keys())
        all_axioms = set(engine.axioms.keys())
        all_terms = set(engine.terms.keys())
        all_theorems = set(engine.theorems.keys())
        all_definitions = all_facts | all_axioms | all_terms | all_theorems

        dangling = all_definitions - reachable

        dangling_facts = dangling & all_facts
        dangling_axioms = dangling & all_axioms
        dangling_terms = dangling & all_terms
        dangling_theorems = dangling & all_theorems

        print(f"\n{'='*60}")
        print("  Diff Reachability Report")
        print(f"{'='*60}")
        print(f"  Total definitions: {len(all_definitions)}")
        print(f"    Facts: {len(all_facts)}")
        print(f"    Axioms: {len(all_axioms)}")
        print(f"    Terms: {len(all_terms)}")
        print(f"    Theorems: {len(all_theorems)}")
        print(f"  Total diffs: {len(engine.diffs)}")
        print("")
        print(f"  Reachable from diffs: {len(all_definitions & reachable)} / {len(all_definitions)}")
        print(f"  Coverage: {100 * len(all_definitions & reachable) / len(all_definitions):.1f}%")
        print("")
        print(f"  Dangling: {len(dangling)}")
        print(f"    Facts: {len(dangling_facts)}")
        print(f"    Axioms: {len(dangling_axioms)}")
        print(f"    Terms: {len(dangling_terms)}")
        print(f"    Theorems: {len(dangling_theorems)}")
        if dangling_facts:
            print("\n  Dangling facts:")
            for name in sorted(dangling_facts):
                print(f"    - {name}")
        if dangling_axioms:
            print("\n  Dangling axioms:")
            for name in sorted(dangling_axioms):
                print(f"    - {name}")
        if dangling_terms:
            print("\n  Dangling terms:")
            for name in sorted(dangling_terms):
                print(f"    - {name}")
        if dangling_theorems:
            print("\n  Dangling theorems:")
            for name in sorted(dangling_theorems):
                print(f"    - {name}")
        print(f"{'='*60}")

        self.assertEqual(dangling, set(), f"Dangling definitions: {len(dangling)} not reachable from any diff")

    def test_top_level_danglings(self):
        """Print definitions that have no parents at all and are not diffs.

        Uses the AST module to build a dependency graph over the loaded
        system, then finds nodes with zero dependents that aren't diffs.
        These are true dead-end definitions — nothing references them.
        """
        engine = self.system.engine
        from parseltongue.core.ast import DirectiveNode

        # Build DirectiveNode list from all engine stores
        nodes: list[DirectiveNode] = []
        order = 0

        # Collect all names that are referenced by diffs, theorems, and term bodies
        from parseltongue.core.atoms import Symbol

        def _collect_symbols(expr):
            if isinstance(expr, Symbol):
                return {str(expr)}
            if isinstance(expr, list):
                result = set()
                for item in expr:
                    result |= _collect_symbols(item)
                return result
            return set()

        # Build a referenced-by map: for each name, who references it?
        referenced_by: dict[str, set[str]] = {}

        for name in list(engine.facts) + list(engine.axioms) + list(engine.terms):
            referenced_by.setdefault(name, set())

        for thm_name, thm in engine.theorems.items():
            for dep in thm.derivation:
                referenced_by.setdefault(dep, set()).add(thm_name)
            referenced_by.setdefault(thm_name, set())

        for diff_name, params in engine.diffs.items():
            referenced_by.setdefault(params["replace"], set()).add(diff_name)
            referenced_by.setdefault(params["with"], set()).add(diff_name)

        for term_name, term in engine.terms.items():
            if term.definition is not None:
                for sym in _collect_symbols(term.definition):
                    referenced_by.setdefault(sym, set()).add(term_name)

        # Rewrite-rule axioms: if an axiom's WFF references a known name,
        # that name effectively "uses" the axiom (the engine applies it
        # as a rewrite rule during evaluation)
        for ax_name, ax in engine.axioms.items():
            for sym in _collect_symbols(ax.wff):
                if sym in engine.terms or sym in engine.facts or sym in engine.axioms or sym in engine.theorems:
                    referenced_by.setdefault(ax_name, set()).add(sym)

        # Top-level danglings: no one references them AND they are not diffs
        diff_names = set(engine.diffs.keys())
        all_names = set(engine.facts) | set(engine.axioms) | set(engine.terms) | set(engine.theorems)
        top_level = {name for name in all_names if not referenced_by.get(name) and name not in diff_names}

        top_facts = sorted(top_level & set(engine.facts))
        top_axioms = sorted(top_level & set(engine.axioms))
        top_terms = sorted(top_level & set(engine.terms))
        top_theorems = sorted(top_level & set(engine.theorems))

        print(f"\n{'='*60}")
        print("  Top-Level Danglings (no parents, not diffs)")
        print(f"{'='*60}")
        print(f"  Total: {len(top_level)}")
        if top_facts:
            print(f"\n  Facts ({len(top_facts)}):")
            for name in top_facts:
                print(f"    - {name}")
        if top_axioms:
            print(f"\n  Axioms ({len(top_axioms)}):")
            for name in top_axioms:
                print(f"    - {name}")
        if top_terms:
            print(f"\n  Terms ({len(top_terms)}):")
            for name in top_terms:
                print(f"    - {name}")
        if top_theorems:
            print(f"\n  Theorems ({len(top_theorems)}):")
            for name in top_theorems:
                print(f"    - {name}")
        print(f"{'='*60}")

        self.assertEqual(len(top_level), 0, f"Found {len(top_level)} top-level danglings: {sorted(top_level)}")

    def test_no_dangling_stability_across_theorem_evaluation(self):
        """The dangling set must be identical before and after evaluating
        all theorems.  Catches mutation of term definitions by evaluate().
        """
        system = load_pltg(CORE_PLTG)
        engine = system.engine

        from parseltongue.core.atoms import Symbol

        def _collect_symbols(expr):
            if isinstance(expr, Symbol):
                return {str(expr)}
            if isinstance(expr, list):
                result = set()
                for item in expr:
                    result |= _collect_symbols(item)
                return result
            return set()

        def _follow_terms(name, visited):
            if name in visited:
                return
            visited.add(name)
            if name in engine.terms:
                term = engine.terms[name]
                if term.definition is not None:
                    for sym in _collect_symbols(term.definition):
                        _follow_terms(sym, visited)

        def _compute_dangling():
            referenced_by_derives = set()
            for thm in engine.theorems.values():
                for dep in thm.derivation:
                    _follow_terms(dep, referenced_by_derives)

            referenced_by_diffs = set()
            for params in engine.diffs.values():
                _follow_terms(params["replace"], referenced_by_diffs)
                _follow_terms(params["with"], referenced_by_diffs)

            referenced = referenced_by_derives | referenced_by_diffs

            # Rewrite-rule axioms: axioms whose WFF references a
            # referenced symbol are themselves in use
            for ax_name, ax in engine.axioms.items():
                if ax_name not in referenced:
                    if _collect_symbols(ax.wff) & referenced:
                        referenced.add(ax_name)

            all_definitions = set(engine.facts.keys()) | set(engine.axioms.keys()) | set(engine.terms.keys())
            return all_definitions - referenced

        dangling_before = deepcopy(_compute_dangling())

        for thm in engine.theorems.values():
            engine.evaluate(thm.wff)

        dangling_after = deepcopy(_compute_dangling())

        new_dangling = dangling_after - dangling_before
        lost_dangling = dangling_before - dangling_after

        report = system.consistency()

        dangling_after_consistency = deepcopy(_compute_dangling())

        lost_dangling_consistency = dangling_before - dangling_after_consistency

        msg = []

        msg.append(f"Were dangling: {sorted(dangling_before)}")

        msg.append(f"After eval: {sorted(dangling_after)}")

        msg.append(f"After consistency: {sorted(dangling_after_consistency)}")

        print(msg)
        self.assertEqual(lost_dangling_consistency, set(), "consistency() changed dangling set:\n" + "\n".join(msg))
        self.assertEqual(dangling_after, dangling_before, "terms eval() changed dangling set:\n" + "\n".join(msg))

        self.assertEqual(dangling_before, dangling_after, "evaluate() changed dangling set:\n" + "\n".join(msg))

    def test_provenance_and_synthetic_diffs(self):
        """Traverse every diff to ground and assert none are fully synthetic.

        For each diff, walks backward through :replace and :with branches,
        following theorem derivation chains, term definitions, and axiom WFFs
        all the way to ground facts.  Asserts that every diff transitively
        reaches at least one fact with verified :evidence (not just :origin).
        """
        engine = self.system.engine

        from parseltongue.core.atoms import Evidence, Symbol
        from parseltongue.core.lang import to_sexp

        def _fmt_value(v):
            if isinstance(v, (list, Symbol)):
                return to_sexp(v)
            return repr(v)

        def _fmt_origin_lines(origin):
            """Return a list of lines describing the origin (no prefix applied)."""
            if isinstance(origin, Evidence):
                status = "grounded" if origin.is_grounded else "UNVERIFIED"
                if origin.verify_manual:
                    status = "manual"
                lines = [f"[{status}] doc={origin.document}"]
                if origin.explanation:
                    lines.append(f"why: {origin.explanation}")
                for q in origin.quotes:
                    qt = q if len(q) <= 80 else q[:77] + "..."
                    lines.append(f'"{qt}"')
                return lines
            if isinstance(origin, str):
                return [origin]
            return [str(origin)]

        def _walk(name, indent=0, visited=None):
            """Recursively walk a symbol to ground, yielding indented lines."""
            if visited is None:
                visited = set()
            prefix = "  " * indent
            tag_prefix = "  " * (indent + 1)

            def _origin_lines(origin):
                result = []
                for ol in _fmt_origin_lines(origin):
                    result.append(f"{tag_prefix}{ol}")
                return result

            lines = []

            # Facts and axioms are terminals — always print, never recurse
            if name in engine.facts:
                fact = engine.facts[name]
                lines.append(f"{prefix}● {name} = {_fmt_value(fact.wff)}  [fact]")
                lines.extend(_origin_lines(fact.origin))
                return lines

            if name in engine.axioms:
                ax = engine.axioms[name]
                lines.append(f"{prefix}∀ {name}: {_fmt_value(ax.wff)}  [axiom]")
                lines.extend(_origin_lines(ax.origin))
                return lines

            # Theorems and terms can form cycles — guard recursion
            if name in visited:
                return [f"{prefix}↻ {name} (seen)"]
            visited.add(name)

            # --- Theorem ---
            if name in engine.theorems:
                thm = engine.theorems[name]
                try:
                    val = engine.evaluate(thm.wff)
                except Exception:
                    val = thm.wff
                lines.append(f"{prefix}⊢ {name} = {_fmt_value(val)}  [theorem]")
                lines.extend(_origin_lines(thm.origin))
                if thm.derivation:
                    lines.append(f"{tag_prefix}:using [{', '.join(thm.derivation)}]")
                    for dep in thm.derivation:
                        lines.extend(_walk(dep, indent + 2, visited))
                return lines

            # --- Term (computed) ---
            if name in engine.terms:
                term = engine.terms[name]
                if term.definition is not None:
                    try:
                        val = engine.evaluate(term.definition)
                    except Exception:
                        val = term.definition
                    lines.append(f"{prefix}≡ {name} = {_fmt_value(val)}  [term]")
                    lines.append(f"{tag_prefix}def: {_fmt_value(term.definition)}")
                    lines.extend(_origin_lines(term.origin))
                    # Follow symbols in the definition
                    deps = _collect_symbols(term.definition)
                    for dep in sorted(deps):
                        if dep in engine.facts or dep in engine.terms or dep in engine.theorems or dep in engine.axioms:
                            lines.extend(_walk(dep, indent + 2, visited))
                else:
                    lines.append(f"{prefix}▪ {name}  [term, forward-declared]")
                    lines.extend(_origin_lines(term.origin))
                return lines

            lines.append(f"{prefix}? {name}  [unknown]")
            return lines

        def _collect_symbols(expr):
            if isinstance(expr, Symbol):
                return {str(expr)}
            if isinstance(expr, list):
                result = set()
                for item in expr:
                    result |= _collect_symbols(item)
                return result
            return set()

        # ---- Collect ground stats ----
        fact_diff_count: dict[str, list[str]] = {}
        diff_grounded: dict[str, list[str]] = {}

        def _is_grounded(name):
            obj = engine.facts.get(name) or engine.terms.get(name) or engine.axioms.get(name)
            if obj is None:
                return False
            origin = obj.origin
            return isinstance(origin, Evidence) and origin.is_grounded

        for diff_name in sorted(engine.diffs):
            params = engine.diffs[diff_name]
            visited: set[str] = set()
            grounded_facts: list[str] = []

            def _collect_ground(name):
                if name in visited:
                    return
                visited.add(name)
                if _is_grounded(name):
                    grounded_facts.append(name)
                if name in engine.facts:
                    fact_diff_count.setdefault(name, []).append(diff_name)
                if name in engine.theorems:
                    for dep in engine.theorems[name].derivation:
                        _collect_ground(dep)
                if name in engine.terms and engine.terms[name].definition is not None:
                    for sym in _collect_symbols(engine.terms[name].definition):
                        if sym in engine.facts or sym in engine.terms or sym in engine.theorems:
                            _collect_ground(sym)

            _collect_ground(params["replace"])
            _collect_ground(params["with"])
            diff_grounded[diff_name] = grounded_facts

        synthetic = [name for name, gf in diff_grounded.items() if not gf]
        unreached = set(engine.facts) - set(fact_diff_count)
        ranked = sorted(fact_diff_count.items(), key=lambda x: -len(x[1]))

        # ---- Write full report to file ----
        import tempfile

        report_dir = os.path.join(tempfile.gettempdir(), "parseltongue_reports")
        os.makedirs(report_dir, exist_ok=True)
        report_path = os.path.join(report_dir, "provenance_report.txt")

        with open(report_path, "w") as rpt:
            rpt.write("PROVENANCE REPORT: Diffs → Ground\n")
            rpt.write("=" * 72 + "\n")

            for diff_name in sorted(engine.diffs):
                params = engine.diffs[diff_name]
                diff_result = engine.eval_diff(diff_name)
                status = "AGREE" if not diff_result.values_diverge else "DIVERGE"
                contam = "" if diff_result.empty else f"  ({len(diff_result.divergences)} downstream)"
                n_ev = len(diff_grounded.get(diff_name, []))

                rpt.write(f"\n{'─'*72}\n")
                rpt.write(f"  DIFF: {diff_name}  [{status}]{contam}  evidence: {n_ev}\n")
                rpt.write(f"    :replace {params['replace']} = {_fmt_value(diff_result.value_a)}\n")
                rpt.write(f"    :with    {params['with']} = {_fmt_value(diff_result.value_b)}\n")

                if not diff_result.empty:
                    rpt.write("    Divergences:\n")
                    for dep, (a, b) in sorted(diff_result.divergences.items()):
                        rpt.write(f"      {dep}: {_fmt_value(a)} → {_fmt_value(b)}\n")

                rpt.write("\n  :replace branch\n")
                visited = set()
                for line in _walk(params["replace"], indent=2, visited=visited):
                    rpt.write(line + "\n")
                rpt.write("\n  :with branch\n")
                for line in _walk(params["with"], indent=2, visited=visited):
                    rpt.write(line + "\n")

            rpt.write(f"\n{'='*72}\n")
            rpt.write("  GROUND CORES: Facts referenced by most diffs\n")
            rpt.write(f"{'='*72}\n")
            for fact_name, diffs_using in ranked[:30]:
                fact = engine.facts[fact_name]
                rpt.write(f"\n  {fact_name} = {_fmt_value(fact.wff)}  [used by {len(diffs_using)} diff(s)]\n")
                rpt.write(f"    diffs: {', '.join(diffs_using)}\n")
                for ol in _fmt_origin_lines(fact.origin):
                    rpt.write(f"    {ol}\n")

            if unreached:
                rpt.write(f"\n  Facts not reached by any diff: {len(unreached)}\n")
                for name in sorted(unreached):
                    rpt.write(f"    - {name}\n")

            if synthetic:
                rpt.write(f"\n  Synthetic diffs (no grounded evidence): {len(synthetic)}\n")
                for name in sorted(synthetic):
                    rpt.write(f"    - {name}\n")

            rpt.write(f"\n{'='*72}\n")

        # ---- Console output ----
        n_grounded_diffs = len(diff_grounded) - len(synthetic)
        n_grounded_facts = sum(1 for f in engine.facts if _is_grounded(f))
        n_total_facts = len(engine.facts)

        def _sbox(text):
            return f"*  {text:<66s}*"

        print(f"\n{'*'*72}")
        print(_sbox("SYNTHETIC DIFF CHECK"))
        print(_sbox(""))
        print(
            _sbox(f"Grounded:  {n_grounded_diffs:>4d} / {len(diff_grounded):<4d}  " f"(reach verified :evidence fact)")
        )
        print(_sbox(f"Synthetic: {len(synthetic):>4d}        " f"(no verified evidence in provenance)"))
        if synthetic:
            print(_sbox(""))
            for name in sorted(synthetic):
                print(_sbox(f"  - {name}"))
        print(f"{'*'*72}")

        print(f"\nProvenance report written to {report_path}")
        print(f"  Open folder: open {report_dir}")

        print(f"\n{'='*72}")
        print("  PROVENANCE SUMMARY")
        print(f"{'='*72}")
        print(f"  Diffs:  {len(engine.diffs)}")
        print(
            f"  Facts:  {n_total_facts}  ({n_grounded_facts} grounded, "
            f"{n_total_facts - n_grounded_facts} origin-only)"
        )
        print("  Top ground cores:")
        for fact_name, diffs_using in ranked[:5]:
            print(f"    {fact_name}  ({len(diffs_using)} diffs)")
        if unreached:
            print(f"  Unreached facts: {len(unreached)}")

        if synthetic:
            print(f"\n{'─'*72}")
            print("  SYNTHETIC DIFFS — full provenance")
            print(f"{'─'*72}")
            for name in sorted(synthetic):
                params = engine.diffs[name]
                print(f"\n  ✗ {name}")
                print(f"    :replace {params['replace']}")
                print(f"    :with    {params['with']}")
                visited = set()
                for line in _walk(params["replace"], indent=3, visited=visited):
                    print(line)
                for line in _walk(params["with"], indent=3, visited=visited):
                    print(line)

        self.assertEqual(
            len(synthetic),
            0,
            f"{len(synthetic)} fully synthetic diff(s) have no grounded evidence "
            f"in their provenance: {sorted(synthetic)}",
        )

    def test_core_to_consequence_report(self):
        """Core-to-consequence ASCII diagram: roots → derives → diffs.

        Builds a dependency graph from the real engine, creates a synthetic
        "output" node that depends on all top-level diffs/derives, then
        renders the core-to-consequence diagram showing how ground facts
        and axioms flow forward through derives into final diffs.

        Node kinds use DSL terminology, not engine internals:
          - fact, axiom: ground nodes (depth 0)
          - term-fwd:  forward-declared (primitive) term, no body
          - term-comp: computed term with a definition body
          - theorem:   derive with :bind (instantiates an axiom)
          - calc:      derive without :bind (pure evaluation)
          - diff:      comparison node

        Asserts minimum compression ratios for best node and overall.
        """
        TARGET_BEST_NODE = 200_000  # best single-node compression ratio
        TARGET_OVERALL = 200  # overall enriched compression ratio

        # --- Input vs output size comparison ---
        module_bytes = 0
        for name, path in self.module_files.items():
            try:
                module_bytes += os.path.getsize(path)
            except OSError:
                pass
        doc_bytes = sum(len(t.encode("utf-8")) for t in self.system.documents.values())
        input_bytes = module_bytes + doc_bytes

        def _hsize(n):
            for unit in ("B", "KB", "MB", "GB"):
                if abs(n) < 1024:
                    return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
                n /= 1024
            return f"{n:.1f} TB"

        print(f"\n{'='*72}")
        print("INPUT vs OUTPUT SIZE")
        print(f"{'='*72}")
        print(f"  Modules ({len(self.module_files):3d} files):  {_hsize(module_bytes):>10s}")
        print(f"  Documents ({len(self.system.documents):3d} loaded): {_hsize(doc_bytes):>10s}")
        print(f"  Total input:               {_hsize(input_bytes):>10s}")

        engine = self.system.engine

        from parseltongue.core.atoms import Evidence, Symbol
        from parseltongue.core.lang import to_sexp

        # --- Estimate full node content size ---
        def _sexp_len(v):
            return len(to_sexp(v)) if v is not None else 0

        def _evidence_len(origin):
            if not isinstance(origin, Evidence):
                return len(str(origin)) if origin else 0
            total = len(origin.document) + len(origin.explanation)
            total += sum(len(q) for q in origin.quotes)
            return total

        wff_sizes = []
        evidence_sizes = []

        for f in engine.facts.values():
            wff_sizes.append(_sexp_len(f.wff))
            evidence_sizes.append(_evidence_len(f.origin))
        for a in engine.axioms.values():
            wff_sizes.append(_sexp_len(a.wff))
            evidence_sizes.append(_evidence_len(a.origin))
        for t in engine.theorems.values():
            wff_sizes.append(_sexp_len(t.wff))
            evidence_sizes.append(_evidence_len(t.origin))
        for t in engine.terms.values():
            wff_sizes.append(_sexp_len(t.definition))
            evidence_sizes.append(_evidence_len(t.origin))

        n_nodes_total = len(wff_sizes)
        avg_wff = sum(wff_sizes) / n_nodes_total if n_nodes_total else 0
        avg_evidence = sum(evidence_sizes) / n_nodes_total if n_nodes_total else 0
        avg_name = (
            sum(len(n) for n in (list(engine.facts) + list(engine.axioms) + list(engine.theorems) + list(engine.terms)))
            / n_nodes_total
            if n_nodes_total
            else 0
        )
        avg_node = avg_name + avg_wff + avg_evidence

        total_wff = sum(wff_sizes)
        total_evidence = sum(evidence_sizes)
        total_names = sum(
            len(n) for n in (list(engine.facts) + list(engine.axioms) + list(engine.theorems) + list(engine.terms))
        )
        total_node_content = total_names + total_wff + total_evidence

        print("\n--- Average node content ---")
        print(f"  {n_nodes_total} nodes total")
        print(f"  Avg name:     {_hsize(avg_name):>10s}")
        print(f"  Avg wff/def:  {_hsize(avg_wff):>10s}")
        print(f"  Avg evidence: {_hsize(avg_evidence):>10s}")
        print(f"  Avg node:     {_hsize(avg_node):>10s}")
        print("\n--- Total node content ---")
        print(f"  Names:        {_hsize(total_names):>10s}")
        print(f"  Wff/defs:     {_hsize(total_wff):>10s}")
        print(f"  Evidence:     {_hsize(total_evidence):>10s}")
        print(f"  Total:        {_hsize(total_node_content):>10s}")

        def _fmt_value(v):
            if isinstance(v, (list, Symbol)):
                return to_sexp(v)
            return repr(v)

        def _collect_symbols(expr):
            if isinstance(expr, Symbol):
                return {str(expr)}
            if isinstance(expr, list):
                r = set()
                for item in expr:
                    r |= _collect_symbols(item)
                return r
            return set()

        # --- Build dependency graph from engine ---
        graph = {}

        def walk(name, visited=None):
            if visited is None:
                visited = set()
            if name in visited or name in graph:
                return
            visited.add(name)
            if name in engine.theorems:
                thm = engine.theorems[name]
                try:
                    val = engine.evaluate(thm.wff)
                except Exception:
                    val = thm.wff
                # theorem = derive with :bind (has axiom in derivation)
                # calc    = derive without :bind (pure evaluation)
                has_bind = any(d in engine.axioms for d in thm.derivation)
                graph[name] = {
                    "kind": "theorem" if has_bind else "calc",
                    "value": val,
                    "inputs": list(thm.derivation),
                }
                for dep in thm.derivation:
                    walk(dep, visited)
            elif name in engine.terms:
                term = engine.terms[name]
                if term.definition is not None:
                    try:
                        val = engine.evaluate(term.definition)
                    except Exception:
                        val = term.definition
                    deps = sorted(
                        d
                        for d in _collect_symbols(term.definition)
                        if d in engine.facts or d in engine.terms or d in engine.theorems or d in engine.axioms
                    )
                    graph[name] = {"kind": "term-comp", "value": val, "inputs": deps}
                    for dep in deps:
                        walk(dep, visited)
                else:
                    graph[name] = {"kind": "term-fwd", "value": "", "inputs": []}
            elif name in engine.facts:
                graph[name] = {
                    "kind": "fact",
                    "value": engine.facts[name].wff,
                    "inputs": [],
                }
            elif name in engine.axioms:
                graph[name] = {
                    "kind": "axiom",
                    "value": engine.axioms[name].wff,
                    "inputs": [],
                }

        # Walk all diffs and top-level theorems into the graph
        top_level = []
        from collections import deque as _deque

        def _count_subtree(node_name, g):
            """Count nodes reachable backwards from node_name."""
            visited = set()
            q = _deque([node_name])
            while q:
                cur = q.popleft()
                if cur in visited or cur not in g:
                    continue
                visited.add(cur)
                q.extend(g[cur]["inputs"])
            return len(visited)

        for diff_name, params in engine.diffs.items():
            walk(params["replace"])
            walk(params["with"])
            # Add diff as a node — value shows subtree sizes
            r_count = _count_subtree(params["replace"], graph)
            w_count = _count_subtree(params["with"], graph)
            graph[diff_name] = {
                "kind": "diff",
                "value": f"diff with tree of {r_count + w_count} nodes",
                "inputs": [params["replace"], params["with"]],
            }
            top_level.append(diff_name)

        # Also walk any theorems not yet reached (standalone derives)
        for name in engine.theorems:
            if name not in graph:
                walk(name)
                top_level.append(name)

        # Create synthetic "output" node that depends on everything top-level
        graph["__output__"] = {
            "kind": "synthetic",
            "value": "",
            "inputs": top_level,
        }

        # --- Depth computation ---
        def compute_depths(g):
            memo = {}

            def depth(n):
                if n in memo:
                    return memo[n]
                if not g[n]["inputs"]:
                    memo[n] = 0
                else:
                    memo[n] = 1 + max(depth(i) for i in g[n]["inputs"] if i in g)
                return memo[n]

            for n in g:
                depth(n)

            # Layout: bump consumers whose fact set subsumes a sibling's
            changed = True
            while changed:
                changed = False
                by_d = {}
                for n, d in memo.items():
                    if d > 0:
                        by_d.setdefault(d, []).append(n)
                for d, nodes in by_d.items():
                    if len(nodes) < 2:
                        continue
                    fact_sets = {}
                    for n in nodes:
                        facts = frozenset(i for i in g[n]["inputs"] if i in g and g[i]["kind"] == "fact")
                        fact_sets[n] = facts
                    for n in nodes:
                        for other in nodes:
                            if n != other and fact_sets[n] > fact_sets[other]:
                                memo[n] = d + 1
                                for m in memo:
                                    if memo[m] > d and n in g[m].get("inputs", []):
                                        memo[m] = max(memo[m], memo[n] + 1)
                                changed = True
                                break
                        if changed:
                            break
            return memo

        depths = compute_depths(graph)
        max_depth = max(depths.values())

        # --- Consumed-at tracking & bar nodes ---
        consumed_at = {n: set() for n in graph}
        for n in graph:
            for inp in graph[n]["inputs"]:
                if inp in graph:
                    consumed_at[inp].add(depths[n])

        bar_set = {
            n for n in graph if len(consumed_at[n]) > 1 and graph[n]["kind"] in ("axiom", "term-comp", "term-fwd")
        }

        bar_groups = []
        assigned = set()
        for bn in sorted(bar_set, key=lambda n: (depths[n], n)):
            if bn in assigned:
                continue
            group = [bn]
            assigned.add(bn)
            for other in sorted(bar_set):
                if other not in assigned and depths[other] == depths[bn] and consumed_at[other] == consumed_at[bn]:
                    group.append(other)
                    assigned.add(other)
            bar_groups.append(group)

        bar_primaries = {g[0] for g in bar_groups}
        bar_secondary = bar_set - bar_primaries

        def snap4(w):
            return ((w + 3) // 4) * 4

        # --- Measure bar column ---
        bar_col = 0
        for group in bar_groups:
            for name in group:
                bar_col = max(bar_col, len(f":{name} ──"))
        bar_col = snap4(bar_col)

        # --- Measure input/result widths per depth ---
        input_widths = {}
        result_widths = {}

        for d in range(1, max_depth + 1):
            consumers = [n for n in graph if depths[n] == d]
            max_iw = 0
            for n in consumers:
                node = graph[n]
                for inp in node["inputs"]:
                    if inp in bar_secondary:
                        continue
                    if inp in bar_primaries:
                        if d == 1:
                            t = f"|── :using {inp} in :{n} ─"
                        else:
                            t = f"|── :using {inp}────"
                    elif graph.get(inp, {}).get("kind") == "fact" and depths.get(inp, 0) == 0:
                        if d == 1:
                            t = f"|   :{inp} ──"
                        else:
                            t = f"|── :using {inp} ──"
                    elif depths.get(inp, 0) > 0 and depths.get(inp, 0) < d:
                        t = f"|── :using {inp} ──"
                    else:
                        t = f"|   :{inp} ──"
                    max_iw = max(max_iw, len(t))
                max_iw = max(max_iw, len(f"|   in :{n} ──"))
            input_widths[d] = max_iw

            max_rw = 0
            for n in consumers:
                val_s = f" (={_fmt_value(graph[n]['value'])})" if graph[n]["value"] else ""
                max_rw = max(max_rw, len(f"|── {n}{val_s} ──"))
            result_widths[d] = max_rw

        # --- Compute rail positions ---
        ts_map = {}  # text_start per depth
        cv_map = {}  # conv per depth
        dp_map = {}  # deposit per depth

        # Only compute rails for depths that have real consumers
        active_depths = sorted(d for d in range(1, max_depth + 1) if any(depths[n] == d for n in graph))

        for d in active_depths:
            consumers = [n for n in graph if depths[n] == d]
            if d == active_depths[0]:
                ts_map[d] = bar_col
            else:
                max_inp_d = 0
                for n in consumers:
                    for inp in graph[n]["inputs"]:
                        if inp in bar_set:
                            continue
                        inp_d = depths.get(inp, 0)
                        if inp_d > 0 and inp_d in dp_map:
                            max_inp_d = max(max_inp_d, inp_d)
                if max_inp_d > 0:
                    ts_map[d] = dp_map[max_inp_d]
                else:
                    # Find the nearest previous depth that has a cv_map entry
                    prev_d = max((pd for pd in active_depths if pd < d), default=None)
                    ts_map[d] = cv_map[prev_d] if prev_d else bar_col

            iw = snap4(input_widths.get(d, 20))
            prev_d = max((pd for pd in active_depths if pd < d), default=None)
            if prev_d and ts_map[d] == cv_map.get(prev_d):
                iw = max(iw, snap4(result_widths.get(prev_d, 0)))
            cv_map[d] = ts_map[d] + iw

            rw = snap4(result_widths.get(d, 20))
            # Check if next active depth's input will share this zone
            next_d = min((nd for nd in active_depths if nd > d), default=None)
            if next_d:
                next_consumers = [n for n in graph if depths[n] == next_d]
                next_deep = any(
                    depths.get(inp, 0) > 0 and inp not in bar_set for n in next_consumers for inp in graph[n]["inputs"]
                )
                if not next_deep:
                    rw = max(rw, snap4(input_widths.get(next_d, 0)))
            dp_map[d] = cv_map[d] + rw

        # --- Emit lines ---
        lines = []

        def pad(s, target_len, ch="─"):
            return s + ch * max(0, target_len - len(s))

        def spc(s, target_len):
            return s + " " * max(0, target_len - len(s))

        active_rails = set()

        def emit(text_pos, text, dash_from=None, trail_rails=True):
            line = ""
            in_dash = False
            for r in sorted(active_rails):
                if r >= text_pos:
                    break
                if dash_from is not None and r == dash_from:
                    line = spc(line, r) + "|"
                    in_dash = True
                elif in_dash:
                    line = pad(line, r, "─") + "|"
                elif dash_from is not None and r > dash_from:
                    line = pad(line, r, "─") + "|"
                    in_dash = True
                else:
                    line = spc(line, r) + "|"
            if in_dash:
                line = pad(line, text_pos, "─")
            else:
                line = spc(line, text_pos)
            line += text
            if trail_rails:
                for r in sorted(active_rails):
                    if r > len(line) - 1:
                        line = spc(line, r) + "|"
            return line

        # Bar headers
        for group in bar_groups:
            for name in group:
                lines.append(pad(f":{name} ", bar_col) + "|")
        if bar_groups:
            active_rails.add(bar_col)

        # Group and sort nodes by depth
        by_depth = {}
        for n in graph:
            by_depth.setdefault(depths[n], []).append(n)

        theorem_order = {name: i for i, name in enumerate(engine.theorems)}
        for d in by_depth:
            if d > 0:
                by_depth[d].sort(key=lambda n: theorem_order.get(n, 999))

        # Render each depth
        # Collect per-depth stats during rendering
        layer_stats = {}  # d -> {consumers: [...], bar_inputs: set, local_facts: set, using_refs: set}

        for d in range(1, max_depth + 1):
            consumers = [n for n in by_depth.get(d, [])]
            if not consumers:
                continue

            ts = ts_map[d]
            cv = cv_map[d]
            dp = dp_map[d]

            layer_stats[d] = {
                "consumers": list(consumers),
                "bar_inputs": set(),
                "local_facts": set(),
                "using_refs": set(),
            }

            for ci, cname in enumerate(consumers):
                cnode = graph[cname]

                bar_inputs = [i for i in cnode["inputs"] if i in bar_primaries]
                local_facts = [
                    i
                    for i in cnode["inputs"]
                    if i not in bar_set and depths.get(i, 0) == 0 and graph.get(i, {}).get("kind") == "fact"
                ]
                using_refs = [
                    i
                    for i in cnode["inputs"]
                    if i not in bar_set and i not in local_facts and depths.get(i, 0) > 0 and depths.get(i, 0) < d
                ]

                layer_stats[d]["bar_inputs"].update(bar_inputs)
                layer_stats[d]["local_facts"].update(local_facts)
                layer_stats[d]["using_refs"].update(using_refs)

                if d == 1:
                    if bar_inputs:
                        text = f"|── :using {bar_inputs[0]} in :{cname} "
                        lines.append(emit(ts, pad(text, cv - ts) + "|"))

                    for lf in local_facts:
                        text = f"|   :{lf} "
                        lines.append(emit(ts, pad(text, cv - ts) + "|"))

                    val_s = f" (={_fmt_value(cnode['value'])})" if cnode["value"] else ""
                    result_text = f"|── {cname}{val_s} "
                    lines.append(emit(cv, pad(result_text, dp - cv) + "|"))
                    active_rails.add(dp)

                    if ci < len(consumers) - 1 or d < max_depth:
                        lines.append(emit(cv, "|"))

                else:
                    if bar_inputs:
                        text = f"|── :using {bar_inputs[0]}────"
                        lines.append(emit(ts, pad(text, cv - ts) + "|", dash_from=bar_col))
                        bar_still_needed = any(
                            depths[n] > d and any(i in bar_primaries for i in graph[n]["inputs"]) for n in graph
                        )
                        if not bar_still_needed:
                            active_rails.discard(bar_col)

                    for ref in local_facts:
                        text = f"|── :using {ref} "
                        lines.append(emit(ts, pad(text, cv - ts) + "|"))

                    for ref in using_refs:
                        ref_dp = dp_map[depths[ref]]
                        text = f"|── :using {ref} "
                        lines.append(emit(ts, pad(text, cv - ts) + "|", dash_from=ref_dp))

                    val_s = f" (={_fmt_value(cnode['value'])})" if cnode["value"] else ""
                    in_text = f"|   in :{cname} "
                    is_last = d == max_depth and ci == len(consumers) - 1
                    # Check: is this actually the last rendered depth?
                    # (max_depth might be __output__)
                    remaining_real = any(depths[n] > d for n in graph)
                    is_last = not remaining_real and ci == len(consumers) - 1

                    if is_last:
                        result_text = f"|── {cname}{val_s}"
                        lines.append(
                            emit(
                                ts,
                                pad(in_text, cv - ts) + result_text,
                                trail_rails=False,
                            )
                        )
                    else:
                        result_text = f"|── {cname}{val_s} "
                        lines.append(
                            emit(
                                ts,
                                pad(in_text, cv - ts) + pad(result_text, dp - cv) + "|",
                            )
                        )
                        active_rails.add(dp)

                    if ci < len(consumers) - 1 or (remaining_real and ci == len(consumers) - 1):
                        lines.append(emit(0, ""))

        # --- Write diagram to file ---
        import tempfile

        report_dir = os.path.join(tempfile.gettempdir(), "parseltongue_reports")
        os.makedirs(report_dir, exist_ok=True)
        out_path = os.path.join(report_dir, "core_to_consequence.txt")
        with open(out_path, "w") as f:
            f.write("CORE → CONSEQUENCE DIAGRAM\n")
            f.write("=" * 72 + "\n\n")
            for line in lines:
                f.write(line + "\n")
            f.write("\n" + "=" * 72 + "\n")
        output_bytes = os.path.getsize(out_path)
        skeleton_ratio = output_bytes / input_bytes if input_bytes else 0
        expand_factor = avg_node / avg_name if avg_name else 1
        # enriched_bytes computed after cons_mass is available (see below)

        # --- Compute all stats before ANY printing ---

        # Build forward adjacency & transitive consequence mass
        fwd = {n: set() for n in graph}
        for n, node in graph.items():
            for inp in node["inputs"]:
                if inp in fwd:
                    fwd[inp].add(n)

        from collections import deque

        # Link term-fwd nodes to their axioms (axioms that reference the term)
        term_fwd_nodes = {n for n in graph if graph[n]["kind"] == "term-fwd"}
        for n in term_fwd_nodes:
            for ax_name, ax_node in list(graph.items()):
                if ax_node["kind"] == "axiom":
                    syms = _collect_symbols(ax_node["value"]) if ax_node["value"] else set()
                    if n in syms or n.split(".")[-1] in syms:
                        fwd[ax_name] |= fwd[n]

        cons_mass = {}
        for n in graph:
            visited = set()
            q = deque(fwd[n])
            while q:
                cur = q.popleft()
                if cur in visited or cur == "__output__":
                    continue
                visited.add(cur)
                q.extend(fwd[cur])
            cons_mass[n] = len(visited)

        total_cons_mass = sum(cons_mass[n] for n in graph if n != "__output__")

        # Imaginary bytes: each diff carries both subtrees in consequence space.
        # For each diff, sum cons_mass of all nodes in both subtrees × avg_node.
        base_enriched = output_bytes * expand_factor
        diff_imaginary_bytes = 0
        for d_name, params in engine.diffs.items():
            if d_name not in graph:
                continue
            for side in (params["replace"], params["with"]):
                visited = set()
                q = deque([side])
                while q:
                    cur = q.popleft()
                    if cur in visited or cur not in graph:
                        continue
                    visited.add(cur)
                    q.extend(graph[cur]["inputs"])
                diff_imaginary_bytes += sum(cons_mass.get(n, 0) for n in visited) * avg_node
        enriched_bytes = base_enriched + diff_imaginary_bytes
        enriched_ratio = enriched_bytes / input_bytes if input_bytes else 0

        # Per-node directive size + compression ratio
        _node_dir_size = {}
        for f in engine.facts.values():
            _node_dir_size[f.name] = len(f.name) + _sexp_len(f.wff) + _evidence_len(f.origin)
        for a in engine.axioms.values():
            _node_dir_size[a.name] = len(a.name) + _sexp_len(a.wff) + _evidence_len(a.origin)
        for t in engine.theorems.values():
            _node_dir_size[t.name] = len(t.name) + _sexp_len(t.wff) + _evidence_len(t.origin)
        for t in engine.terms.values():
            _node_dir_size[t.name] = len(t.name) + _sexp_len(t.definition) + _evidence_len(t.origin)

        # Diff content = full transitive input tree on both sides
        def _subtree_size(node_name):
            """Sum of _node_dir_size for all nodes reachable backwards from node_name."""
            visited = set()
            q = deque([node_name])
            total = 0
            while q:
                cur = q.popleft()
                if cur in visited or cur not in graph:
                    continue
                visited.add(cur)
                total += _node_dir_size.get(cur, 0)
                q.extend(graph[cur]["inputs"])
            return total

        for d_name, params in engine.diffs.items():
            _node_dir_size[d_name] = len(d_name) + _subtree_size(params["replace"]) + _subtree_size(params["with"])

        def _node_ratio(n):
            """Compression ratio for a single node."""
            ds = _node_dir_size.get(n, 0)
            if not ds or not total_cons_mass:
                return 0.0
            share = cons_mass.get(n, 0) / total_cons_mass * enriched_bytes
            return share / ds

        best_node_name = max(
            (n for n in graph if n != "__output__"),
            key=lambda n: _node_ratio(n),
        )
        best_node_r = _node_ratio(best_node_name)
        overall_ratio = enriched_ratio

        # Node counts
        n_nodes = len(graph) - 1
        n_facts = sum(1 for n in graph if graph[n]["kind"] == "fact")
        n_axioms = sum(1 for n in graph if graph[n]["kind"] == "axiom")
        n_term_fwd = sum(1 for n in graph if graph[n]["kind"] == "term-fwd")
        n_term_comp = sum(1 for n in graph if graph[n]["kind"] == "term-comp")
        n_terms = n_term_fwd + n_term_comp
        n_theorems = sum(1 for n in graph if graph[n]["kind"] == "theorem")
        n_calcs = sum(1 for n in graph if graph[n]["kind"] == "calc")
        n_derives = n_theorems + n_calcs
        n_diffs = sum(1 for n in graph if graph[n]["kind"] == "diff")

        all_counts = {
            "fact": n_facts,
            "axiom": n_axioms,
            "term": n_terms,
            "term-fwd": n_term_fwd,
            "term-comp": n_term_comp,
            "derive": n_derives,
            "theorem": n_theorems,
            "calc": n_calcs,
            "diff": n_diffs,
        }

        _FLAVOR_TO_AGG = {
            "fact": "fact",
            "axiom": "axiom",
            "diff": "diff",
            "term-fwd": "term",
            "term-comp": "term",
            "theorem": "derive",
            "calc": "derive",
        }
        kind_mass = {}
        for n in graph:
            if n == "__output__":
                continue
            k = graph[n]["kind"]
            kind_mass[k] = kind_mass.get(k, 0) + cons_mass[n]
            agg_k = _FLAVOR_TO_AGG[k]
            if agg_k != k:
                kind_mass[agg_k] = kind_mass.get(agg_k, 0) + cons_mass[n]

        kind_avg = {}
        for k, m in kind_mass.items():
            cnt = all_counts.get(k, 1)
            kind_avg[k] = m / cnt

        flavor_counts = {
            "fact": n_facts,
            "axiom": n_axioms,
            "diff": n_diffs,
            "term-fwd": n_term_fwd,
            "term-comp": n_term_comp,
            "theorem": n_theorems,
            "calc": n_calcs,
        }
        flavor_mass = {k: kind_mass.get(k, 0) for k in flavor_counts}

        flavor_avg = {}
        for k, m in flavor_mass.items():
            cnt = flavor_counts[k]
            flavor_avg[k] = m / cnt if cnt else 0

        flavor_directive_size = {}
        for f in engine.facts.values():
            k = "fact"
            sz = len(f.name) + _sexp_len(f.wff) + _evidence_len(f.origin)
            flavor_directive_size[k] = flavor_directive_size.get(k, 0) + sz
        for a in engine.axioms.values():
            k = "axiom"
            sz = len(a.name) + _sexp_len(a.wff) + _evidence_len(a.origin)
            flavor_directive_size[k] = flavor_directive_size.get(k, 0) + sz
        for t in engine.theorems.values():
            has_bind = any(d in engine.axioms for d in t.derivation)
            k = "theorem" if has_bind else "calc"
            sz = len(t.name) + _sexp_len(t.wff) + _evidence_len(t.origin)
            flavor_directive_size[k] = flavor_directive_size.get(k, 0) + sz
        for t in engine.terms.values():
            k = "term-comp" if t.definition is not None else "term-fwd"
            sz = len(t.name) + _sexp_len(t.definition) + _evidence_len(t.origin)
            flavor_directive_size[k] = flavor_directive_size.get(k, 0) + sz
        for d_name, params in engine.diffs.items():
            sz = len(d_name) + len(params["replace"]) + len(params["with"])
            flavor_directive_size["diff"] = flavor_directive_size.get("diff", 0) + sz

        # ===================================================================
        # PRINTS START HERE — all computation is done above
        # ===================================================================

        def _box(text):
            return f"*  {text:<66s}*"

        # --- Compression targets first ---
        bn_pass = "PASS" if best_node_r >= TARGET_BEST_NODE else "FAIL"
        ov_pass = "PASS" if overall_ratio >= TARGET_OVERALL else "FAIL"

        print(f"\n{'*'*72}")
        print(_box("COMPRESSION TARGETS"))
        print(_box(""))
        print(_box(f"Best node: {best_node_name:<30s} {best_node_r:>12,.0f}x  {bn_pass}"))
        print(_box(f"           target: >= {TARGET_BEST_NODE:,}x"))
        print(_box(f"Overall:   enriched ratio {' '*15} {overall_ratio:>12,.1f}x  {ov_pass}"))
        print(_box(f"           target: >= {TARGET_OVERALL:,}x"))
        print(f"{'*'*72}")

        print(f"\nDiagram written to {out_path}")
        print(f"  Open folder: open {report_dir}")

        print("\n--- Diagram output vs sources ---")
        print(f"  Source modules:            {_hsize(module_bytes):>10s}  ({len(self.module_files)} files)")
        print(f"  Source documents:          {_hsize(doc_bytes):>10s}  ({len(self.system.documents)} loaded)")
        print(f"  Total input:              {_hsize(input_bytes):>10s}")
        print(
            f"  Total node content:       {_hsize(total_node_content):>10s}  "
            f"(names {_hsize(total_names)} + wff {_hsize(total_wff)} + evidence {_hsize(total_evidence)})"
        )
        print(f"  Diagram (names only):     {_hsize(output_bytes):>10s}")
        print(
            f"  Diagram (with content):   {_hsize(enriched_bytes):>10s}  "
            f"(×{expand_factor:.1f}: {_hsize(avg_name)} name → {_hsize(avg_node)} full)"
        )
        print(f"\n  Skeleton ratio:           {skeleton_ratio:>10.1f}x  (diagram / input)")
        print(
            f"  Base enriched:            {_hsize(base_enriched):>10s}  ({base_enriched / input_bytes if input_bytes else 0:.1f}x)"
        )
        print(f"  Diff imaginary:           {_hsize(diff_imaginary_bytes):>10s}  ({len(engine.diffs)} diffs)")
        print(f"  Enriched ratio:           {enriched_ratio:>10.1f}x  (enriched / input)")

        # --- Flavor compression ratio ---
        print("\n--- Flavor compression ratio ---")
        print(
            f"  {'flavor':10s} {'count':>5s}  {'dir size':>8s}  "
            f"{'cons %':>6s}  {'output share':>12s}  {'ratio':>8s}"
        )
        for k in sorted(
            flavor_counts,
            key=lambda f: -(
                flavor_mass.get(f, 0) / total_cons_mass * enriched_bytes / max(flavor_directive_size.get(f, 1), 1)
            ),
        ):
            cnt = flavor_counts[k]
            dir_sz = flavor_directive_size.get(k, 0)
            cons_share = flavor_mass.get(k, 0) / total_cons_mass if total_cons_mass else 0
            output_share = cons_share * enriched_bytes
            ratio = output_share / dir_sz if dir_sz else 0
            bar_w = int(min(ratio / 100, 1.0) * 40) + 1
            print(
                f"  {k:10s} {cnt:>5d}  {_hsize(dir_sz):>8s}  "
                f"{cons_share*100:>5.1f}%  {_hsize(output_share):>12s}  "
                f"{ratio:>7.1f}x  {'█' * bar_w}"
            )

        # --- Aggregated stats ---
        print(f"\n{'='*72}")
        print("CORE → CONSEQUENCE STATS")
        print(f"{'='*72}\n")

        print(
            f"  Nodes: {n_nodes}  (facts={n_facts}, axioms={n_axioms}, terms={n_terms}, derives={n_derives}, diffs={n_diffs})"
        )
        print(f"    terms:   {n_term_fwd} primitive (term-fwd)  +  {n_term_comp} computed (term-comp)")
        print(f"    derives: {n_theorems} theorem (with :bind)  +  {n_calcs} calc (no :bind)")
        print(f"  Bar nodes (shared roots): {len(bar_set)}")
        print(f"  Active depths: {len(active_depths)}, max depth: {max_depth}")
        print(f"  Diagram lines: {len(lines)}")

        print("\n--- Node kind distribution ---")
        for k, c in sorted(all_counts.items(), key=lambda x: -x[1]):
            pct = c / n_nodes * 100
            bar_w = int(pct / 2) + 1
            print(f"  {k:10s} {c:4d}  {pct:5.1f}%  {'█' * bar_w}")

        print("\n--- Node kind consequence mass (with overlap) ---")
        max_mass = max(kind_mass.values()) or 1
        for k, m in sorted(kind_mass.items(), key=lambda x: -x[1]):
            bar_w = int(m / max_mass * 40) + 1
            print(f"  {k:10s} {m:6d}  {'█' * bar_w}")

        print("\n--- Consequence per node (mass / count) ---")
        max_avg = max(kind_avg.values()) or 1
        for k, avg in sorted(kind_avg.items(), key=lambda x: -x[1]):
            cnt = all_counts.get(k, 0)
            total = kind_mass[k]
            bar_w = int(avg / max_avg * 40) + 1
            label = f"{k} ({total}/{cnt})"
            print(f"  {label:28s} {avg:7.1f}  {'█' * bar_w}")

        print("\n--- Flavor distribution ---")
        for k, c in sorted(flavor_counts.items(), key=lambda x: -x[1]):
            pct = c / n_nodes * 100
            bar_w = int(pct / 2) + 1
            print(f"  {k:10s} {c:4d}  {pct:5.1f}%  {'█' * bar_w}")

        print("\n--- Flavor consequence mass ---")
        max_fm = max(flavor_mass.values()) or 1
        for k, m in sorted(flavor_mass.items(), key=lambda x: -x[1]):
            bar_w = int(m / max_fm * 40) + 1
            print(f"  {k:10s} {m:6d}  {'█' * bar_w}")

        print("\n--- Flavor consequence per node ---")
        max_fa = max(flavor_avg.values()) or 1
        for k, avg in sorted(flavor_avg.items(), key=lambda x: -x[1]):
            cnt = flavor_counts[k]
            total = flavor_mass[k]
            bar_w = int(avg / max_fa * 40) + 1
            label = f"{k} ({total}/{cnt})"
            print(f"  {label:28s} {avg:7.1f}  {'█' * bar_w}")

        # --- Layer distribution: nodes and consequence mass per band ---
        # Layer 0 = bar nodes, layers 1+ from layer_stats.
        # Fibonacci-sized buckets after layer 0.
        print("\n--- Layer distribution (nodes × consequence mass) ---")

        bar_nodes = sorted(bar_set)
        bar_mass = sum(cons_mass[n] for n in bar_nodes)
        layer_keys = sorted(layer_stats.keys())

        bands = [("0", len(bar_nodes), bar_mass)]
        max_band_mass = bar_mass

        # Build fibonacci bucket boundaries for layers 1+
        if layer_keys:
            fibs = [1, 2]
            while fibs[-1] < layer_keys[-1]:
                fibs.append(fibs[-2] + fibs[-1])
            band_start = layer_keys[0]
            for fib in fibs:
                band_end = band_start + fib - 1
                if band_start > layer_keys[-1]:
                    break
                band_end = min(band_end, layer_keys[-1])
                cnt = 0
                mass = 0
                for d in layer_keys:
                    if band_start <= d <= band_end:
                        for n in layer_stats[d]["consumers"]:
                            cnt += 1
                            mass += cons_mass[n]
                label = f"{band_start}-{band_end}" if band_start != band_end else f"{band_start}"
                bands.append((label, cnt, mass))
                max_band_mass = max(max_band_mass, mass)
                band_start = band_end + 1

        max_band_nodes = max(cnt for _, cnt, _ in bands) or 1
        max_band_mass = max_band_mass or 1
        for label, cnt, mass in bands:
            n_w = int(cnt / max_band_nodes * 40) + 1
            m_w = int(mass / max_band_mass * 40) + 1
            print(f"  {label:>7s}  {cnt:4d} nodes  {mass:5d} cons  {'░' * n_w}{'█' * m_w}")

        # --- Top 5 bar nodes: sub-computation paths ---
        print("\n--- Top 5 bar nodes: consequence breakdown ---")
        top5_bars = sorted(bar_set, key=lambda n: -cons_mass[n])[:5]
        for root in top5_bars:
            rc = cons_mass[root]
            pct_total = rc / n_nodes * 100
            bar_w = int(pct_total / 2) + 1
            rr = _node_ratio(root)
            print(f"\n  {root} ({rc}/{n_nodes} = {pct_total:.1f}%)  {rr:.0f}x")
            print(f"    {'█' * bar_w} {pct_total:.1f}%")

            children = sorted(
                (c for c in fwd[root] if c != "__output__"),
                key=lambda c: -cons_mass[c],
            )[:5]
            for child in children:
                cc = cons_mass[child]
                cpct = cc / n_nodes * 100
                cbar = int(cpct / 2) + 1
                ckind = graph[child]["kind"]
                cr = _node_ratio(child)
                print(f"      └─ {ckind:8s} {child}  ({cc} = {cpct:.1f}%)  {cr:.0f}x")
                print(f"         {'▓' * cbar} {cpct:.1f}%")

                grandchildren = sorted(
                    (g for g in fwd[child] if g != "__output__"),
                    key=lambda g: -cons_mass[g],
                )[:5]
                for gc in grandchildren:
                    gc_c = cons_mass[gc]
                    gc_pct = gc_c / n_nodes * 100
                    gc_bar = int(gc_pct / 2) + 1
                    gc_kind = graph[gc]["kind"]
                    gc_r = _node_ratio(gc)
                    print(f"            └─ {gc_kind:8s} {gc}  ({gc_c} = {gc_pct:.1f}%)  {gc_r:.0f}x")
                    print(f"               {'░' * gc_bar} {gc_pct:.1f}%")

        # __output__
        out_inputs = graph["__output__"]["inputs"]
        print(f"\n  __output__ (depth {depths['__output__']}): {len(out_inputs)} top-level inputs")

        # --- Per layer (detailed, last) ---
        print("\n--- Per layer ---")

        # Depth 0: bar nodes
        print(f"  depth   0: {len(bar_set):3d} bar nodes")
        bar_ranked = sorted(bar_set, key=lambda n: -cons_mass[n])[:20]
        for n in bar_ranked:
            kind = graph[n]["kind"]
            nr = _node_ratio(n)
            print(f"      {kind:8s} {n}  → {cons_mass[n]} consequences  {nr:.0f}x")

        # Depths 1+: from rendering data
        for d in sorted(layer_stats):
            ls = layer_stats[d]
            consumers = ls["consumers"]
            k_counts = {}
            for n in consumers:
                k = graph[n]["kind"]
                k_counts[k] = k_counts.get(k, 0) + 1
            parts = ", ".join(f"{v} {k}" for k, v in sorted(k_counts.items()))
            n_bi = len(ls["bar_inputs"])
            n_lf = len(ls["local_facts"])
            n_ref = len(ls["using_refs"])
            feeds = f"  feeds: {n_bi} bar, {n_lf} facts, {n_ref} refs"
            print(f"  depth {d:3d}: {len(consumers):3d} nodes  ({parts}){feeds}")
            ranked = sorted(consumers, key=lambda n: -cons_mass[n])[:20]
            for n in ranked:
                kind = graph[n]["kind"]
                nr = _node_ratio(n)
                print(f"      {kind:8s} {n}  → {cons_mass[n]} consequences  {nr:.0f}x")

        print(f"\n{'='*72}")

        self.assertGreaterEqual(
            best_node_r,
            TARGET_BEST_NODE,
            f"Best single-node compression {best_node_r:,.0f}x < {TARGET_BEST_NODE:,}x target "
            f"(node: {best_node_name})",
        )
        self.assertGreaterEqual(
            overall_ratio,
            TARGET_OVERALL,
            f"Overall enriched compression {overall_ratio:,.1f}x < {TARGET_OVERALL:,}x target",
        )
