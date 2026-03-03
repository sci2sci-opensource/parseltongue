"""
Demo: Documentation Validation

Scenario: A library README contains several internally inconsistent
claims: the config table says max_sessions=10 but no code or spec
backs it up, the security section makes unverifiable audit claims,
and the session management section contradicts itself about hashing.
Parseltongue extracts facts and catches every inconsistency.
"""

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

    s = System(overridable=True)
    print("=" * 60)
    print("Parseltongue — Documentation Validation")
    print("=" * 60)

    # ----------------------------------------------------------
    # Phase 0: Load the README
    # ----------------------------------------------------------
    print("\n--- Phase 0: Load README ---")
    doc_dir = os.path.join(os.path.dirname(__file__), "resources")
    s.load_document("README", os.path.join(doc_dir, "readme.txt"))
    print(f"  Loaded {len(s.documents)} document(s)")

    # ----------------------------------------------------------
    # Phase 1: Extract facts from the README
    # ----------------------------------------------------------
    print("\n--- Phase 1: Extract facts ---")

    load_source(
        s,
        """
        (fact python-requirement "3.9"
          :evidence (evidence "README"
            :quotes ("Requires Python 3.9 or higher.")
            :explanation "Minimum Python version"))

        (fact default-algorithm "sha256"
          :evidence (evidence "README"
            :quotes ("algorithm | sha256  | Hashing algorithm")
            :explanation "Default algorithm from config table"))

        (fact default-expiry 1800
          :evidence (evidence "README"
            :quotes ("expiry    | 1800    | Token lifetime in seconds")
            :explanation "Default expiry from config table"))

        (fact max-token-lifetime 7200
          :evidence (evidence "README"
            :quotes ("The maximum token lifetime is 2 hours (7200 seconds).")
            :explanation "Maximum allowed token lifetime"))

        (fact max-sessions-config 10
          :evidence (evidence "README"
            :quotes ("max_sessions | 10  | Maximum concurrent sessions")
            :explanation "Max sessions from config table"))

        (fact prose-expiry-minutes 30
          :evidence (evidence "README"
            :quotes ("expire after 30 minutes by default")
            :explanation "Expiry in prose section"))

        (fact session-hash-claim "sha256"
          :evidence (evidence "README"
            :quotes ("Session IDs use the same hashing algorithm as tokens (SHA-256).")
            :explanation "README claims sessions use SHA-256"))

        (fact security-audit-claim "three firms"
          :evidence (evidence "README"
            :quotes ("audited by three independent security firms")
            :explanation "Unverifiable security audit claim"))

        (fact zero-vulns-claim true
          :evidence (evidence "README"
            :quotes ("contains zero known vulnerabilities as of version 2.0")
            :explanation "Unverifiable vulnerability claim"))
    """,
    )

    _print_list(s.list_facts())

    # ----------------------------------------------------------
    # Phase 2: Internal consistency checks
    # ----------------------------------------------------------
    print("\n--- Phase 2: Internal consistency checks ---")

    load_source(
        s,
        """
        (defterm prose-expiry-seconds
            (* prose-expiry-minutes 60)
            :evidence (evidence "README"
              :quotes ("expire after 30 minutes by default")
              :explanation "Convert prose claim to seconds for comparison"))

        (derive prose-matches-config
            (= (* prose-expiry-minutes 60) default-expiry)
            :using (prose-expiry-minutes default-expiry))

        (diff expiry-prose-vs-config
            :replace default-expiry
            :with prose-expiry-seconds)
    """,
    )

    print("  Prose says 30 min, config table says 1800s:")
    print(f"  30 * 60 = {s.evaluate(s.terms['prose-expiry-seconds'].definition)}")
    print(f"  Config table: {s.facts['default-expiry']['value']}")
    print(f"  Match: {s.eval_diff('expiry-prose-vs-config')}")

    # ----------------------------------------------------------
    # Phase 3: Fabricated claims — things the README asserts
    #          that cannot be verified from the document alone
    # ----------------------------------------------------------
    print("\n--- Phase 3: Unverifiable claims ---")
    print("  The README claims:")
    print("    - Audited by three independent security firms")
    print("    - Zero known vulnerabilities")
    print("  These are accepted as facts but have no cross-reference.")
    print("  An LLM might also fabricate additional claims...")

    load_source(
        s,
        """
        (fact ip-binding-claim true
          :evidence (evidence "README"
            :quotes ("Each session is bound to a single IP address for security.")
            :explanation "Session IP binding claim"))

        (fact auto-session-claim true
          :evidence (evidence "README"
            :quotes ("Sessions are created automatically on first token generation.")
            :explanation "Auto session creation claim"))
    """,
    )

    # Now an LLM hallucination: claiming rate limiting exists
    load_source(
        s,
        """
        (fact rate-limiting true
          :evidence (evidence "README"
            :quotes ("Rate limiting is enforced at 100 requests per minute per user.")
            :explanation "Rate limiting configuration"))
    """,
    )

    print("\n  rate-limiting fact accepted but quote verification fails:")
    _print_list(s.list_facts())

    # ----------------------------------------------------------
    # Phase 4: Derive from the fabricated claim
    # ----------------------------------------------------------
    print("\n--- Phase 4: Fabrication propagation ---")

    load_source(
        s,
        """
        (derive rate-limiting-secure
            (= rate-limiting true)
            :using (rate-limiting))
    """,
    )

    print("  Derivation from unverified fact inherits taint:")
    _print_list(s.list_theorems())

    # ----------------------------------------------------------
    # Phase 5: Config table vs max lifetime consistency
    # ----------------------------------------------------------
    print("\n--- Phase 5: Expiry vs max lifetime ---")

    load_source(
        s,
        """
        (derive default-within-max
            (< default-expiry max-token-lifetime)
            :using (default-expiry max-token-lifetime))
    """,
    )

    print("  Default (1800) < max (7200):")
    _print_list(s.list_theorems())

    # ----------------------------------------------------------
    # Phase 6: Consistency report
    # ----------------------------------------------------------
    print("\n--- Phase 6: Consistency report ---")
    report = s.consistency()
    print(f"\n  {report}")

    # ----------------------------------------------------------
    # Summary
    # ----------------------------------------------------------
    print("\n" + "=" * 60)
    print("Documentation issues found:")
    print("  1. rate-limiting: fabricated — no such text in README")
    print("  2. security audit & zero-vulns: unverifiable marketing claims")
    print("  3. max_sessions=10: present in config table but unusually high")
    print("  4. Expiry prose vs config table: CONSISTENT (30min = 1800s)")
    print(f"\nFinal system: {s}")


if __name__ == "__main__":
    main()
