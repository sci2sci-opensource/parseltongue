"""
Demo: Parseltongue DSL — Counting Observations & Apple Arithmetic.

Scenario: Build arithmetic from observational field notes about counting
physical objects, then apply it to an orchard harvest inventory.
Starts with a minimal custom system (successor, basic arithmetic — no logic
operators), grounds counting properties in observations, then solves
real inventory problems with full provenance.
"""

import os
import sys
import json
import logging
import operator

from engine import System, load_source
from lang import Symbol


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

    # Start from nothing — all operations introduced from observations
    s = System(initial_env={}, overridable=True)
    print("=" * 60)
    print("Parseltongue DSL — Counting Observations & Apple Arithmetic")
    print("=" * 60)

    # ----------------------------------------------------------
    # Phase 0: Load source documents
    # ----------------------------------------------------------
    print("\n--- Phase 0: Load source documents ---")
    doc_dir = os.path.join(os.path.dirname(__file__), 'resources')
    s.load_document("Counting Observations",
                    os.path.join(doc_dir, "counting_observations.txt"))
    s.load_document("Orchard Inventory",
                    os.path.join(doc_dir, "orchard_inventory.txt"))
    print(f"  Loaded {len(s.documents)} source documents")
    for name in s.documents:
        print(f"    - {name}")

    # ----------------------------------------------------------
    # Phase 1: Minimal system — just successor and equality
    # ----------------------------------------------------------
    print("\n--- Phase 1: Truly minimal system ---")
    print(f"  Starting with: {s}")
    print(f"  Operators: succ, =  (nothing else)")
    print(f"  (succ 0) = {s.evaluate([SUCC, 0])}")
    print(f"  (succ (succ 0)) = {s.evaluate([SUCC, [SUCC, 0]])}")
    print(f"  (= (succ 0) 1) = {s.evaluate([Symbol('='), [SUCC, 0], 1])}")

    # ----------------------------------------------------------
    # Phase 2: Ground zero and successor in observations
    # ----------------------------------------------------------
    print("\n--- Phase 2: Ground zero and successor ---")

    load_source(s, """
        (fact zero 0
          :evidence (evidence "Counting Observations"
            :quotes ("An empty basket contains zero apples")
            :explanation "Zero is the count of an empty collection"))

        (axiom succ-closure (= (succ zero) 1)
          :evidence (evidence "Counting Observations"
            :quotes ("Every count is reached by adding one to the previous count")
            :explanation "Successor of any natural number is a natural number"))
    """)

    print(f"  System now: {s}")
    _print_list(s.list_facts())

    # ----------------------------------------------------------
    # Phase 3: Build natural numbers via successor
    # ----------------------------------------------------------
    print("\n--- Phase 3: Build natural numbers ---")

    load_source(s, """
        (defterm one (succ zero)
          :evidence (evidence "Counting Observations"
            :quotes ("The first apple makes one")
            :explanation "1 = succ(0)"))

        (defterm two (succ one)
          :evidence (evidence "Counting Observations"
            :quotes ("the second makes two")
            :explanation "2 = succ(1)"))

        (defterm three (succ two)
          :evidence (evidence "Counting Observations"
            :quotes ("Combining 3 apples with 2 apples always gives 5 apples")
            :explanation "3 = succ(2), referenced in addition trial"))

        (defterm four (succ three)
          :evidence (evidence "Counting Observations"
            :quotes ("If both baskets have 4 apples, after swapping they still each have 4")
            :explanation "4 = succ(3), referenced in swap invariance"))

        (defterm five (succ four)
          :evidence (evidence "Counting Observations"
            :quotes ("If basket A has 5 and basket B has 3, then basket A has more")
            :explanation "5 = succ(4), referenced in comparison"))
    """)

    for name in ['one', 'two', 'three', 'four', 'five']:
        print(f"  {name} = {s.evaluate(Symbol(name))}")

    # ----------------------------------------------------------
    # Phase 4: Ground arithmetic properties
    # ----------------------------------------------------------
    print("\n--- Phase 4: Arithmetic properties from observations ---")

    load_source(s, """
        (axiom add-identity (= (+ zero zero) zero)
          :evidence (evidence "Counting Observations"
            :quotes ("Adding nothing to a basket does not change the count")
            :explanation "Additive identity: n + 0 = n"))

        (axiom add-commutative (= (+ three two) (+ two three))
          :evidence (evidence "Counting Observations"
            :quotes ("The order of combining does not matter")
            :explanation "Commutativity: a + b = b + a"))

        (axiom combining-gives-sum (= (+ three two) five)
          :evidence (evidence "Counting Observations"
            :quotes ("Combining 3 apples with 2 apples always gives 5 apples")
            :explanation "Addition produces the sum of both counts"))
    """)

    _print_list(s.list_axioms())

    # ----------------------------------------------------------
    # Phase 5: Ingest morning harvest
    # ----------------------------------------------------------
    print("\n--- Phase 5: Morning harvest ---")

    load_source(s, """
        (fact alice-morning 3
          :evidence (evidence "Orchard Inventory"
            :quotes ("Alice picked 3 apples from the east grove")
            :explanation "Alice's morning count"))

        (fact bob-morning 5
          :evidence (evidence "Orchard Inventory"
            :quotes ("Bob picked 5 apples from the west grove")
            :explanation "Bob's morning count"))

        (defterm morning-total
            (+ alice-morning bob-morning)
            :evidence (evidence "Orchard Inventory"
              :quotes ("Combined morning harvest was 8 apples")
              :explanation "Sum of Alice and Bob's morning picks"))

        (defterm bob-picked-more
            (> bob-morning alice-morning)
            :evidence (evidence "Orchard Inventory"
              :quotes ("Bob picked more apples than Alice in the morning")
              :explanation "Bob's count exceeds Alice's"))
    """)

    print(f"  Alice morning: {s.facts['alice-morning']['value']}")
    print(f"  Bob morning: {s.facts['bob-morning']['value']}")
    print(f"  Morning total: {s.evaluate(s.terms['morning-total'].definition)}")
    print(f"  Bob > Alice? {s.evaluate(s.terms['bob-picked-more'].definition)}")

    # ----------------------------------------------------------
    # Phase 6: Derive morning results
    # ----------------------------------------------------------
    print("\n--- Phase 6: Derive morning results ---")

    load_source(s, """
        (derive morning-is-8
            (= (+ alice-morning bob-morning) 8)
            :using (alice-morning bob-morning))

        (derive bob-beat-alice
            (> bob-morning alice-morning)
            :using (alice-morning bob-morning))
    """)

    _print_list(s.list_axioms())

    # ----------------------------------------------------------
    # Phase 7: Ingest afternoon harvest
    # ----------------------------------------------------------
    print("\n--- Phase 7: Afternoon harvest ---")

    load_source(s, """
        (fact carol-afternoon 4
          :evidence (evidence "Orchard Inventory"
            :quotes ("Carol picked 4 apples from the south grove")
            :explanation "Carol's afternoon count"))

        (fact alice-afternoon 2
          :evidence (evidence "Orchard Inventory"
            :quotes ("Alice picked 2 more apples from the east grove")
            :explanation "Alice's afternoon count"))

        (defterm afternoon-total
            (+ carol-afternoon alice-afternoon)
            :evidence (evidence "Orchard Inventory"
              :quotes ("Combined afternoon harvest was 6 apples")
              :explanation "Sum of Carol and Alice's afternoon picks"))

        (defterm alice-daily
            (+ alice-morning alice-afternoon)
            :evidence (evidence "Orchard Inventory"
              :quotes ("Alice's daily total is 5 apples")
              :explanation "Alice's combined morning + afternoon"))
    """)

    print(f"  Carol afternoon: {s.facts['carol-afternoon']['value']}")
    print(f"  Alice afternoon: {s.facts['alice-afternoon']['value']}")
    print(f"  Afternoon total: {s.evaluate(s.terms['afternoon-total'].definition)}")
    print(f"  Alice daily: {s.evaluate(s.terms['alice-daily'].definition)}")

    # ----------------------------------------------------------
    # Phase 8: Derive daily totals
    # ----------------------------------------------------------
    print("\n--- Phase 8: Derive daily totals ---")

    load_source(s, """
        (defterm daily-total
            (+ morning-total afternoon-total)
            :evidence (evidence "Orchard Inventory"
              :quotes ("Total harvest for the day was 14 apples")
              :explanation "Grand total = morning + afternoon"))

        (defterm morning-advantage
            (- morning-total afternoon-total)
            :evidence (evidence "Orchard Inventory"
              :quotes ("The morning shift outproduced the afternoon by 2 apples")
              :explanation "Difference between shift totals"))

        (derive total-is-14
            (= (+ (+ alice-morning bob-morning) (+ carol-afternoon alice-afternoon)) 14)
            :using (alice-morning bob-morning carol-afternoon alice-afternoon))

        (derive alice-daily-is-5
            (= (+ alice-morning alice-afternoon) 5)
            :using (alice-morning alice-afternoon))
    """)

    print(f"  Daily total: {s.evaluate(s.terms['daily-total'].definition)}")
    print(f"  Morning advantage: {s.evaluate(s.terms['morning-advantage'].definition)}")
    _print_list(s.list_axioms())

    # ----------------------------------------------------------
    # Phase 9: Diff — what if Alice picked more?
    # ----------------------------------------------------------
    print("\n--- Phase 9: Diff — what if Alice picked 4 in the morning? ---")

    load_source(s, """
        (fact alice-morning-alt 4
          :origin "Hypothetical: Alice picks 4 instead of 3")

        (diff alice-check
            :replace alice-morning
            :with alice-morning-alt)
    """)

    print(f"  {s.eval_diff('alice-check')}")

    # ----------------------------------------------------------
    # Phase 10: Provenance
    # ----------------------------------------------------------
    print("\n--- Phase 10: Provenance --- ")

    print("  Provenance of total-is-14:")
    print(json.dumps(s.provenance('total-is-14'), indent=2))

    print("\n  Provenance of alice-daily-is-5:")
    print(json.dumps(s.provenance('alice-daily-is-5'), indent=2))

    # ----------------------------------------------------------
    # Phase 11: Consistency report
    # ----------------------------------------------------------
    print("\n--- Phase 11: Consistency report ---")
    report = s.consistency()
    print(f"  {report}")

    # Resolve plain-origin items
    print("\n  Resolving unverified items...")
    load_source(s, """
           (fact alice-morning-alt 3
             :origin "Hypothetical: Alice picks 4 instead of 3")
       """)
    s.verify_manual('alice-morning-alt')
    s.retract('four')
    report = s.consistency()
    print(f"\n  After verification:")
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
    print("Key insight: Arithmetic properties emerge from observational")
    print("field notes about counting physical objects. The system then")
    print("applies these grounded operations to a real inventory problem,")
    print("with every derived fact traceable to source evidence.")
    print("=" * 60)


if __name__ == '__main__':
    main()
