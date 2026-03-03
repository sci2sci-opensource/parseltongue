"""
Demo: Parseltongue DSL — Counting Observations & Apple Arithmetic.

Scenario: Build arithmetic from observational field notes about counting
physical objects, then apply it to an orchard harvest inventory.
Starts with a completely empty system, introduces symbols as terms,
states parameterized axioms grounded in evidence, and derives
concrete theorems via :bind — all in successor notation.
"""

import json
import logging
import os
import sys

from parseltongue.core import System, load_source


def _print_list(items):
    for item in items:
        if isinstance(item, dict):
            origin = item.get("origin", "")
            tag = str(origin) if hasattr(origin, "is_grounded") else f"[origin: {origin}]"
            print(f"  {item['name']} = {item['value']} {tag}")
        else:
            print(f"  {item}")


def main():
    plog = logging.getLogger("parseltongue")
    plog.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("  [%(levelname)s] %(message)s"))
    plog.addHandler(handler)

    s = System(initial_env={}, overridable=True)
    print("=" * 60)
    print("Parseltongue DSL — Counting Observations & Apple Arithmetic")
    print("=" * 60)

    # ----------------------------------------------------------
    # Phase 0: Load source documents
    # ----------------------------------------------------------
    print("\n--- Phase 0: Load source documents ---")
    doc_dir = os.path.join(os.path.dirname(__file__), "resources")
    s.load_document("Counting Observations", os.path.join(doc_dir, "counting_observations.txt"))
    s.load_document("Eden Inventory", os.path.join(doc_dir, "eden_inventory.txt"))
    print(f"  Loaded {len(s.documents)} source documents")

    # ----------------------------------------------------------
    # Phase 1: Introduce primitive symbols
    # ----------------------------------------------------------
    print("\n--- Phase 1: Introduce primitive symbols ---")
    print(f"  Starting with: {s}  (empty!)")

    load_source(
        s,
        r"""
        (defterm zero
          :evidence (evidence "Counting Observations"
            :quotes ("We decided to mark an empty basket as \"zero\"")
            :explanation "Zero: the label for an empty collection"))

        (defterm succ
          :evidence (evidence "Counting Observations"
            :quotes ("every pile is reached by adding one more apple to the previous pile")
            :explanation "Successor: produces the next pile"))

        (defterm =
          :evidence (evidence "Counting Observations"
            :quotes ("If both baskets have 🍎🍎🍎🍎 apples, after swapping they still each have 🍎🍎🍎🍎")
            :explanation "Equality: two piles that look the same"))

        (defterm +
          :evidence (evidence "Counting Observations"
            :quotes ("Combining 🍎🍎🍎 apples with 🍎🍎 apples always gives 🍎🍎🍎🍎🍎 apples")
            :explanation "Addition: combining two collections"))

        (defterm -
          :evidence (evidence "Counting Observations"
            :quotes ("The difference is found by removing apples from the larger pile until it matches the smaller")
            :explanation "Subtraction: finding the difference"))

        (defterm >
          :evidence (evidence "Counting Observations"
            :quotes ("If basket A has 🍎🍎🍎🍎🍎 and basket B has 🍎🍎🍎, then basket A has more")
            :explanation "Greater-than: heavier basket has more"))

        (defterm *
          :evidence (evidence "Counting Observations"
            :quotes ("Multiplication is a shortcut for combining equal groups")
            :explanation "Multiplication: repeated addition"))
    """,
    )

    print("  Introduced: zero, succ, =, +, -, >, *")
    print(f"  System: {s}")

    # ----------------------------------------------------------
    # Phase 2: Axioms of Peano arithmetic
    # ----------------------------------------------------------
    print("\n--- Phase 2: Axioms of Peano arithmetic ---")

    load_source(
        s,
        r"""
        (axiom eq-reflexive (= ?x ?x)
          :evidence (evidence "Counting Observations"
            :quotes ("If both baskets have 🍎🍎🍎🍎 apples, after swapping they still each have 🍎🍎🍎🍎")
            :explanation "Equality is reflexive: any pile equals itself"))

        (axiom add-identity (= (+ ?n zero) ?n)
          :evidence (evidence "Counting Observations"
            :quotes ("Adding nothing to a basket does not change the pile")
            :explanation "Additive identity: n + 0 = n"))

        (axiom add-succ (= (+ ?n (succ ?m)) (succ (+ ?n ?m)))
          :evidence (evidence "Counting Observations"
            :quotes ("every pile is reached by adding one more apple to the previous pile")
            :explanation "Addition step: n + S(m) = S(n + m)"))

        (axiom add-commutative (= (+ ?a ?b) (+ ?b ?a))
          :evidence (evidence "Counting Observations"
            :quotes ("The order of combining does not matter")
            :explanation "Commutativity: a + b = b + a"))

        (axiom mul-zero (= (* ?n zero) zero)
          :evidence (evidence "Counting Observations"
            :quotes ("We decided to mark an empty basket as \"zero\"")
            :explanation "Multiplication by zero: n * 0 = 0"))

        (axiom mul-succ (= (* ?n (succ ?m)) (+ (* ?n ?m) ?n))
          :evidence (evidence "Counting Observations"
            :quotes ("Multiplication is a shortcut for combining equal groups")
            :explanation "Multiplication step: n * S(m) = n*m + n"))
    """,
    )

    print("  Axioms:")
    _print_list(s.list_axioms())

    # ----------------------------------------------------------
    # Phase 3: Derive concrete theorems via :bind
    # ----------------------------------------------------------
    print("\n--- Phase 3: Concrete theorems via :bind ---")

    # 3 + 0 = 3
    load_source(
        s,
        """
        (derive three-plus-zero add-identity
            :bind ((?n (succ (succ (succ zero)))))
            :using (add-identity succ))
    """,
    )

    # commutativity: SSS0 + SS0 = SS0 + SSS0
    load_source(
        s,
        """
        (derive commute-3-2 add-commutative
            :bind ((?a (succ (succ (succ zero))))
                   (?b (succ (succ zero))))
            :using (add-commutative succ zero))
    """,
    )

    # addition step: SSS0 + S0 = S(SSS0 + 0)
    load_source(
        s,
        """
        (derive add-step-3-1 add-succ
            :bind ((?n (succ (succ (succ zero))))
                   (?m zero))
            :using (add-succ zero))
    """,
    )

    print("  Concrete theorems:")
    for name in ["three-plus-zero", "commute-3-2", "add-step-3-1"]:
        ax = s.theorems[name]
        print(f"    {ax}")

    # ----------------------------------------------------------
    # Phase 4: Orchard inventory — apply arithmetic to real data
    # ----------------------------------------------------------
    print("\n--- Phase 4: Orchard inventory ---")

    load_source(
        s,
        """
        (defterm eve-morning (succ (succ (succ zero)))
          :evidence (evidence "Eden Inventory"
            :quotes ("Eve picked 🍎🍎🍎 apples from the east grove")
            :explanation "Eve's morning count: SSS0"))

        (defterm adam-morning (succ (succ (succ (succ (succ zero)))))
          :evidence (evidence "Eden Inventory"
            :quotes ("Adam picked 🍎🍎🍎🍎🍎 apples from the west grove")
            :explanation "Adam's morning count: SSSSS0"))

        (defterm morning-total (+ eve-morning adam-morning)
          :evidence (evidence "Eden Inventory"
            :quotes ("Combined morning harvest was 🍎🍎🍎🍎🍎🍎🍎🍎 apples")
            :explanation "Sum of Eve and Adam's morning picks"))

        (defterm adam-picked-more (> adam-morning eve-morning)
          :evidence (evidence "Eden Inventory"
            :quotes ("Adam picked more apples than Eve in the morning")
            :explanation "Adam's count exceeds Eve's"))
    """,
    )

    print("  Terms:")
    _print_list(s.list_terms())

    # ----------------------------------------------------------
    # Phase 5: Derive morning commutativity from axiom
    # ----------------------------------------------------------
    print("\n--- Phase 5: Morning commutativity ---")

    load_source(
        s,
        """
        (derive morning-commutes add-commutative
            :bind ((?a eve-morning) (?b adam-morning))
            :using (add-commutative eve-morning adam-morning)
            :evidence (evidence "Eden Inventory"
              :quotes ("Combined morning harvest was 🍎🍎🍎🍎🍎🍎🍎🍎 apples")
              :explanation "eve + adam = adam + eve"))
    """,
    )

    ax = s.theorems["morning-commutes"]
    print(f"  {ax}")

    # ----------------------------------------------------------
    # Phase 6: Afternoon harvest
    # ----------------------------------------------------------
    print("\n--- Phase 6: Afternoon harvest ---")

    load_source(
        s,
        """
        (defterm serpent-afternoon (succ (succ (succ (succ zero))))
          :evidence (evidence "Eden Inventory"
            :quotes ("Serpent picked 🍎🍎🍎🍎 apples from the south grove")
            :explanation "Serpent's afternoon count: SSSS0"))

        (defterm eve-afternoon (succ (succ zero))
          :evidence (evidence "Eden Inventory"
            :quotes ("Eve picked 🍎🍎 more apples from the east grove")
            :explanation "Eve's afternoon count: SS0"))

        (defterm afternoon-total (+ serpent-afternoon eve-afternoon)
          :evidence (evidence "Eden Inventory"
            :quotes ("Combined afternoon harvest was 🍎🍎🍎🍎🍎🍎 apples")
            :explanation "Sum of Serpent and Eve's afternoon picks"))

        (defterm eve-daily (+ eve-morning eve-afternoon)
          :evidence (evidence "Eden Inventory"
            :quotes ("Eve's daily total is 🍎🍎🍎🍎🍎 apples")
            :explanation "Eve's combined morning + afternoon"))

        (defterm daily-total (+ morning-total afternoon-total)
          :evidence (evidence "Eden Inventory"
            :quotes ("Total harvest for the day was 🍎🍎🍎🍎🍎🍎🍎🍎🍎🍎🍎🍎🍎🍎 apples")
            :explanation "Grand total = morning + afternoon"))

        (defterm morning-advantage (- morning-total afternoon-total)
          :evidence (evidence "Eden Inventory"
            :quotes ("The morning shift outproduced the afternoon by 🍎🍎 apples")
            :explanation "Difference between shift totals"))
    """,
    )

    print("  Terms:")
    for name in [
        "serpent-afternoon",
        "eve-afternoon",
        "afternoon-total",
        "eve-daily",
        "daily-total",
        "morning-advantage",
    ]:
        t = s.terms[name]
        print(f"    {t}")

    # ----------------------------------------------------------
    # Phase 7: Diff — what if Eve tried the forbidden apple?
    # ----------------------------------------------------------
    print("\n--- Phase 7: Diff — what if Eve tried the forbidden apple? ---")

    load_source(
        s,
        """
        (defterm eve-morning-alt (succ (succ zero))
          :origin "Hypothetical: Eve tried the forbidden apple — SS0 instead of SSS0")

        (diff eve-check
            :replace eve-morning
            :with eve-morning-alt)
    """,
    )

    # ----------------------------------------------------------
    # Phase 8: Provenance
    # ----------------------------------------------------------
    print("\n--- Phase 8: Provenance ---")

    print("  Provenance of morning-commutes:")
    print(json.dumps(s.provenance("morning-commutes"), indent=2))

    # ----------------------------------------------------------
    # Phase 9: Consistency report
    # ----------------------------------------------------------
    print("\n--- Phase 9: Consistency report ---")
    report = s.consistency()
    print(f"  {report}")

    print("\n  Resolving unverified items...")
    s.verify_manual("eve-morning-alt")
    s.verify_manual("eq-reflexive")
    s.verify_manual("=")
    report = s.consistency()
    print("\n  After verification:")
    print(f"  {report}")

    print("\n  Resolving identity items...")
    load_source(
        s,
        """
        (defterm eve-morning-alt (succ (succ (succ zero)))
          :origin "Hypothetical: Eve picks SSSS0 instead of SSS0")
    """,
    )
    s.verify_manual("eve-morning-alt")
    report = s.consistency()
    print("\n  After verification:")
    print(f"  {report}")

    # ----------------------------------------------------------
    # Summary
    # ----------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"Final system: {s}")
    print("\nAll axioms:")
    _print_list(s.list_axioms())
    print("\nAll theorems:")
    _print_list(s.list_theorems())

    print("\n" + "=" * 60)
    print("Peano arithmetic built from observational field notes.")
    print("Every symbol introduced as a term, every property stated")
    print("as a parameterized axiom, concrete theorems via :bind.")
    print("All in successor notation — no numeric primitives.")
    print("=" * 60)


if __name__ == "__main__":
    main()
