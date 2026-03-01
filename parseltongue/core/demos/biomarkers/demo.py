"""
Demo: Parseltongue DSL — Biomarker Evidence Conflict.

Scenario: Two papers report on fecal calprotectin as a diagnostic marker
for IBD. Paper A supports its diagnostic value (high sensitivity). Paper B
challenges its specificity (elevated in non-IBD conditions). The system
ingests both, derives contradictory conclusions, and flags the conflict.
"""

import json
import logging
import os
import sys

from parseltongue.core import System, load_source


def _print_list(items):
    for item in items:
        if isinstance(item, dict):
            origin = item.get('origin', '')
            tag = str(origin) if hasattr(origin, 'is_grounded') else f"[origin: {origin}]"
            print(f"  {item['name']} = {item['value']} {tag}")
        else:
            print(f"  {item}")


def main():
    plog = logging.getLogger('parseltongue')
    plog.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('  [%(levelname)s] %(message)s'))
    plog.addHandler(handler)

    s = System(overridable=True)
    print("=" * 60)
    print("Parseltongue DSL — Biomarker Evidence Conflict")
    print("=" * 60)

    # ----------------------------------------------------------
    # Phase 0: Load source papers
    # ----------------------------------------------------------
    print("\n--- Phase 0: Load source papers ---")
    doc_dir = os.path.join(os.path.dirname(__file__), 'resources')
    s.load_document("Paper A: Diagnostic", os.path.join(doc_dir, "paper_diagnostic.txt"))
    s.load_document("Paper B: Specificity", os.path.join(doc_dir, "paper_specificity.txt"))
    print(f"  Loaded {len(s.documents)} source papers")
    for name in s.documents:
        print(f"    - {name}")

    # ----------------------------------------------------------
    # Phase 1: Base system
    # ----------------------------------------------------------
    print("\n--- Phase 1: Base system ---")
    print(f"  Starting with: {s}")

    # ----------------------------------------------------------
    # Phase 2: Ingest Paper A — diagnostic value
    # ----------------------------------------------------------
    print("\n--- Phase 2: Ingest Paper A (diagnostic value) ---")

    load_source(
        s,
        """
        (fact calprotectin-sensitivity 93
          :evidence (evidence "Paper A: Diagnostic"
            :quotes ("Sensitivity of 93% was observed in distinguishing IBD from IBS")
            :explanation "Reported sensitivity for IBD vs IBS distinction"))

        (fact calprotectin-threshold 250
          :evidence (evidence "Paper A: Diagnostic"
            :quotes ("Fecal calprotectin levels above 250 µg/g strongly correlate with endoscopically confirmed active intestinal inflammation")
            :explanation "Clinical threshold for active inflammation"))

        (fact calprotectin-npv 96
          :evidence (evidence "Paper A: Diagnostic"
            :quotes ("The negative predictive value was 96%")
            :explanation "NPV for ruling out IBD"))

        (defterm reliable-marker
            (> calprotectin-sensitivity 90)
            :evidence (evidence "Paper A: Diagnostic"
              :quotes ("Calprotectin is recommended as a first-line non-invasive test before colonoscopy")
              :explanation "Paper A recommends calprotectin as first-line test, implying reliability"))
    """,
    )

    print(f"  System now: {s}")
    _print_list(s.list_facts())

    # ----------------------------------------------------------
    # Phase 3: Ingest Paper B — specificity concerns
    # ----------------------------------------------------------
    print("\n--- Phase 3: Ingest Paper B (specificity concerns) ---")

    load_source(
        s,
        """
        (fact calprotectin-specificity 67
          :evidence (evidence "Paper B: Specificity"
            :quotes ("Specificity of only 67% was observed when non-IBD inflammatory conditions were included")
            :explanation "Low specificity in broader patient populations"))

        (fact elevated-in-non-ibd true
          :evidence (evidence "Paper B: Specificity"
            :quotes ("Calprotectin is elevated in multiple non-IBD conditions")
            :explanation "Calprotectin not specific to IBD"))

        (fact nsaid-false-positive-rate 43
          :evidence (evidence "Paper B: Specificity"
            :quotes ("Among patients taking regular NSAIDs, 43% had elevated calprotectin above the standard 50 µg/g cutoff despite no evidence of IBD")
            :explanation "High false-positive rate in NSAID users"))

        (defterm standalone-diagnostic
            (and (> calprotectin-sensitivity 90)
                 (> calprotectin-specificity 90))
            :evidence (evidence "Paper B: Specificity"
              :quotes ("Calprotectin should not be used as a standalone diagnostic tool for IBD")
              :explanation "Paper B argues standalone use requires both high sensitivity AND specificity"))
    """,
    )

    print(f"  System now: {s}")
    _print_list(s.list_facts())

    # ----------------------------------------------------------
    # Phase 4: Derive contradictory conclusions
    # ----------------------------------------------------------
    print("\n--- Phase 4: Derive conclusions from each paper ---")

    load_source(
        s,
        """
        (derive marker-is-reliable
            (> calprotectin-sensitivity 90)
            :using (calprotectin-sensitivity))

        (derive marker-not-standalone
            (not (> calprotectin-specificity 90))
            :using (calprotectin-specificity))
    """,
    )

    print("  From Paper A: marker-is-reliable = True (sensitivity 93 > 90)")
    print("  From Paper B: marker-not-standalone = True (specificity 67 < 90)")
    _print_list(s.list_axioms())

    # ----------------------------------------------------------
    # Phase 5: Cross-paper synthesis — clinical utility
    # ----------------------------------------------------------
    print("\n--- Phase 5: Cross-paper synthesis ---")

    load_source(
        s,
        """
        (defterm clinical-utility
            (if (and reliable-marker standalone-diagnostic)
                "use-alone"
                "use-with-confirmation")
            :origin "Synthesized from both papers")
    """,
    )

    utility = s.evaluate(s.terms['clinical-utility'].definition)
    print(f"  clinical-utility = \"{utility}\"")
    print("  (High sensitivity but low specificity → needs confirmatory testing)")

    standalone = s.evaluate(s.terms['standalone-diagnostic'].definition)
    reliable = s.evaluate(s.terms['reliable-marker'].definition)
    print(f"\n  reliable-marker = {reliable}")
    print(f"  standalone-diagnostic = {standalone}")

    # ----------------------------------------------------------
    # Phase 6: Diff — what if specificity were higher?
    # ----------------------------------------------------------
    print("\n--- Phase 6: Diff — what if specificity were 95%? ---")

    load_source(
        s,
        """
        (fact calprotectin-specificity-optimistic 95
          :origin "Hypothetical: what if combined approach achieved 95%?")

        (diff specificity-check
            :replace calprotectin-specificity
            :with calprotectin-specificity-optimistic)
    """,
    )

    diff_result = s.eval_diff('specificity-check')
    print("\n  Diff result:")
    print(f"  {diff_result}")

    # ----------------------------------------------------------
    # Phase 7: Provenance trace
    # ----------------------------------------------------------
    print("\n--- Phase 7: Provenance — tracing clinical-utility ---")

    print("  Provenance of marker-is-reliable:")
    print(json.dumps(s.provenance('marker-is-reliable'), indent=2))

    print("\n  Provenance of marker-not-standalone:")
    print(json.dumps(s.provenance('marker-not-standalone'), indent=2))

    # ----------------------------------------------------------
    # Phase 8: Consistency report
    # ----------------------------------------------------------
    print("\n--- Phase 8: Consistency report ---")
    report = s.consistency()
    print("\n  Full report:")
    print(f"  {report}")

    # ----------------------------------------------------------
    # Phase 9: Resolve — verify and reconcile
    # ----------------------------------------------------------
    print("\n--- Phase 9: Resolve consistency issues ---")

    # Verify plain-origin items
    s.verify_manual('clinical-utility')
    s.verify_manual('calprotectin-specificity-optimistic')

    report = s.consistency()
    print("\n  After verification:")
    print(f"  {report}")

    # ----------------------------------------------------------
    # Summary
    # ----------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"Final system: {s}")
    print("\nAll facts:")
    _print_list(s.list_facts())
    print("\nAll terms:")
    _print_list(s.list_terms())
    print("\nAll axioms:")
    _print_list(s.list_axioms())

    print("\n" + "=" * 60)
    print("Key insight: Both papers are individually verified, but the")
    print("system reveals the tension — calprotectin is sensitive but")
    print("not specific. The formal system makes the conflict explicit")
    print("and traceable to source evidence.")
    print("=" * 60)


if __name__ == '__main__':
    main()
