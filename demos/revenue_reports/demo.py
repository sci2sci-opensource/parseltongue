"""
Demo: Parseltongue DSL in action.

Scenario: Analyzing company performance from multiple documents.
Shows the system growing from a minimal base as evidence is ingested,
with quote verification, fabrication propagation, and manual override.
"""

import os
import sys
import json
import logging

from engine import System, load_source
from lang import Symbol


def print_facts(facts):
    for f in facts:
        origin = f['origin']
        if isinstance(origin, dict):
            status = "grounded" if origin.get('grounded') else "UNVERIFIED"
            tag = f"[evidence: {origin['document']} ({status})]"
        else:
            tag = f"[origin: {origin}]"
        print(f"  {f['name']} = {f['value']} {tag}")


def print_terms(terms):
    for t in terms:
        origin = t['origin']
        if isinstance(origin, dict):
            status = "grounded" if origin.get('grounded') else "UNVERIFIED"
            tag = f"[evidence: {origin['document']} ({status})]"
        else:
            tag = f"[origin: {origin}]"
        print(f"  {t['name']}: {t['definition']} {tag}")


def print_axioms(axioms):
    for a in axioms:
        if a['derived']:
            tag = f"[derived from: {', '.join(a.get('derivation', []))}]"
        else:
            origin = a['origin']
            if isinstance(origin, dict):
                status = "grounded" if origin.get('grounded') else "UNVERIFIED"
                tag = f"[evidence: {origin['document']} ({status})]"
            else:
                tag = f"[origin: {origin}]"
        print(f"  {a['name']}: {a['wff']} {tag}")


def main():
    plog = logging.getLogger('parseltongue')
    plog.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('  [%(levelname)s] %(message)s'))
    plog.addHandler(handler)

    s = System(overridable=True)
    print("=" * 60)
    print("Parseltongue DSL — Self-Extending Formal System")
    print("=" * 60)

    # ----------------------------------------------------------
    # Phase 0: Load source documents
    # ----------------------------------------------------------
    print("\n--- Phase 0: Load source documents ---")
    doc_dir = os.path.join(os.path.dirname(__file__), 'resources')
    s.load_document("Q3 Report", os.path.join(doc_dir, "q3_report.txt"))
    s.load_document("FY2024 Targets Memo", os.path.join(doc_dir, "targets_memo.txt"))
    s.load_document("Bonus Policy Doc", os.path.join(doc_dir, "bonus_policy.txt"))
    print(f"  Loaded {len(s.documents)} source documents")
    for name in s.documents:
        print(f"    - {name}")

    # ----------------------------------------------------------
    # Phase 1: Base system — just arithmetic, logic, comparison
    # ----------------------------------------------------------
    print("\n--- Phase 1: Base system ---")
    print(f"Starting with: {s}")
    print(f"  (+ 2 3) = {s.evaluate([Symbol('+'), 2, 3])}")
    print(f"  (> 15 10) = {s.evaluate([Symbol('>'), 15, 10])}")

    # ----------------------------------------------------------
    # Phase 2: Ingest Q3 Report with quote-verified evidence
    # ----------------------------------------------------------
    print("\n--- Phase 2: Ingest Q3 Report (with quote verification) ---")

    load_source(s, """
        (fact revenue-q3 15.0
          :evidence (evidence "Q3 Report"
            :quotes ("Q3 revenue was $15M")
            :explanation "Dollar revenue figure from Q3 report"))

        (fact revenue-q3-growth 15
          :evidence (evidence "Q3 Report"
            :quotes ("up 15% year-over-year")
            :explanation "YoY growth percentage"))
    """)

    print(f"  System now: {s}")
    print_facts(s.list_facts())

    # ----------------------------------------------------------
    # Phase 3: Ingest Targets Memo with evidence
    # ----------------------------------------------------------
    print("\n--- Phase 3: Ingest Targets Memo (with quote verification) ---")

    load_source(s, """
        (fact growth-target 10
          :evidence (evidence "FY2024 Targets Memo"
            :quotes ("Revenue growth target for FY2024: 10%")
            :explanation "The board-set target percentage"))

        (defterm beat-target
            (> revenue-q3-growth growth-target)
            :evidence (evidence "FY2024 Targets Memo"
              :quotes ("Exceeding the growth target is defined as achieving year-over-year revenue growth above the stated target percentage")
              :explanation "Definition of what it means to beat the target"))
    """)

    print(f"  System now: {s}")

    # ----------------------------------------------------------
    # Phase 4: LLM-guided derivation (grounded sources)
    # ----------------------------------------------------------
    print("\n--- Phase 4: Derivation from verified sources ---")

    load_source(s, """
        (derive target-exceeded
            (> revenue-q3-growth growth-target)
            :using (revenue-q3-growth growth-target))
    """)

    result = s.evaluate(s.terms['beat-target'].definition)
    print(f"  beat-target evaluates to: {result}")
    print_axioms(s.list_axioms())

    # ----------------------------------------------------------
    # Phase 5: Provenance trace with verification details
    # ----------------------------------------------------------
    print("\n--- Phase 5: Provenance trace ---")
    prov = s.provenance('target-exceeded')
    print(json.dumps(prov, indent=2))

    # ----------------------------------------------------------
    # Phase 6: Fabricated quote — flagged, not rejected
    # ----------------------------------------------------------
    print("\n--- Phase 6: Fabricated quote detection ---")

    load_source(s, """
        (fact fake-metric 999
          :evidence (evidence "Q3 Report"
            :quotes ("Q3 revenue was $999M, a record-breaking quarter")
            :explanation "This quote does not exist in the document"))
    """)

    print(f"  fake-metric accepted but flagged:")
    print_facts(s.list_facts())

    # ----------------------------------------------------------
    # Phase 7: Fabrication propagation through derivation
    # ----------------------------------------------------------
    print("\n--- Phase 7: Fabrication propagation ---")

    load_source(s, """
        (derive uses-fake
            (> fake-metric 0)
            :using (fake-metric))
    """)

    print("  Derivation from unverified source:")
    print_axioms(s.list_axioms())

    # ----------------------------------------------------------
    # Phase 8: Manual override
    # ----------------------------------------------------------
    print("\n--- Phase 8: Manual override ---")
    print("  Before override:")
    print_facts(s.list_facts())

    s.verify_manual('fake-metric')

    print("  After override:")
    print_facts(s.list_facts())

    # ----------------------------------------------------------
    # Phase 9: Cross-document inference with verified evidence
    # ----------------------------------------------------------
    print("\n--- Phase 9: Cross-document inference ---")

    load_source(s, """
        (fact base-salary 150000
          :evidence (evidence "Bonus Policy Doc"
            :quotes ("Base salary for eligible employees is $150,000")
            :explanation "Base salary from HR policy"))

        (fact bonus-rate 0.20
          :evidence (evidence "Bonus Policy Doc"
            :quotes ("Bonus is 20% of base salary if growth target is exceeded")
            :explanation "Bonus rate from policy"))

        (defterm bonus-amount
            (if (> revenue-q3-growth growth-target)
                (* base-salary bonus-rate)
                0)
            :evidence (evidence "Bonus Policy Doc"
              :quotes ("Bonus is 20% of base salary if growth target is exceeded"
                       "Eligibility requires that the quarterly revenue growth exceeds the stated annual growth target")
              :explanation "Bonus calculation formula and eligibility criteria"))
    """)

    amount = s.evaluate(s.terms['bonus-amount'].definition)
    print(f"  Bonus amount: ${amount:,.0f}")

    load_source(s, """
        (derive bonus-confirmed
            (> (* base-salary bonus-rate) 0)
            :using (base-salary bonus-rate))
    """)

    print(f"\n  Full provenance of bonus:")
    print(json.dumps(s.provenance('bonus-confirmed'), indent=2))

    # ----------------------------------------------------------
    # Phase 10: Diff — cross-source consistency check
    # ----------------------------------------------------------
    print("\n--- Phase 10: Diff — cross-source consistency check ---")

    # Add absolute revenue figures so we can compute growth independently
    load_source(s, """
        (fact revenue-q3-abs 230
          :origin "Q3 Report, revenue table")

        (fact revenue-q2 210
          :origin "Q2 Report, revenue table")

        ;; Compute growth from absolute figures
        (defterm revenue-q3-growth-computed
            (* (/ (- revenue-q3-abs revenue-q2) revenue-q2) 100)
            :origin "Derived from Q2/Q3 absolute revenue")
    """)

    computed = s.evaluate(s.terms['revenue-q3-growth-computed'].definition)
    print(f"  Reported growth: 15%")
    print(f"  Computed growth: {computed:.2f}%")

    # Now diff: what changes if we use the computed value instead?
    load_source(s, """
        (diff growth-check
            :replace revenue-q3-growth
            :with revenue-q3-growth-computed)
    """)

    print(f"\n  Diff result:")
    print(json.dumps(s.eval_diff('growth-check'), indent=2, default=str))

    # ----------------------------------------------------------
    # Phase 11: System consistency report
    # ----------------------------------------------------------
    print("\n--- Phase 11: System consistency report ---")
    report = s.consistency()
    print(f"\n  Full report:")
    print(json.dumps(report, indent=2, default=str))

    # ----------------------------------------------------------
    # Phase 12: Fix consistency issues
    # ----------------------------------------------------------
    print("\n--- Phase 12: Resolve consistency issues ---")

    # Fix 1: Verify base-salary evidence (quote failed due to line-break formatting)
    print("\n  Fix 1: Verify base-salary (formatting edge case)")
    s.verify_manual('base-salary')

    # Fix 2: Rederive tainted axioms now that sources are grounded
    print("\n  Fix 2: Rederive tainted axioms")
    s.rederive('bonus-confirmed')
    s.rederive('uses-fake')

    # Fix 3: Manually verify plain-origin items
    print("\n  Fix 3: Verify plain-origin items")
    s.verify_manual('revenue-q3-abs')
    s.verify_manual('revenue-q2')
    s.verify_manual('revenue-q3-growth-computed')

    # Fix 4: Correct revenue-q3-abs — if Q2=210 and growth=15%, Q3=241.5
    # overridable=True: auto-overwrites and recomputes dependent diffs
    print("\n  Fix 4: Correct revenue-q3-abs (auto-recomputes diffs)")
    s.set_fact('revenue-q3-abs', 241.5,
               "Corrected: 210 * 1.15 = 241.5 to match reported 15% growth")
    s.verify_manual('revenue-q3-abs')

    # Check consistency again
    print("\n  Consistency after fixes:")
    report = s.consistency()
    print(f"\n  Full report:")
    print(json.dumps(report, indent=2, default=str))

    # ----------------------------------------------------------
    # Summary
    # ----------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"Final system: {s}")
    print("\nAll axioms:")
    print_axioms(s.list_axioms())
    print("\nAll terms:")
    print_terms(s.list_terms())
    print("\nAll facts:")
    print_facts(s.list_facts())


if __name__ == '__main__':
    main()
