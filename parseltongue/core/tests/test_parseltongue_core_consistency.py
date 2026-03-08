"""Self-validation: load core.pltg and check consistency."""

import os
import unittest
from copy import deepcopy

from ..loader import load_pltg

CORE_PLTG = os.path.join(os.path.dirname(__file__), "..", "validation", "core.pltg")


class TestParseltongueCoreConsistency(unittest.TestCase):

    @classmethod
    def setUpClass(cls):

        cls.system = load_pltg(CORE_PLTG)

    def test_core_consistency(self):
        report = self.system.consistency()
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
