"""
Demo: Code-Specification Cross-Validation

Scenario: An API specification says tokens expire in 30 minutes,
max 3 sessions, and MD5 must not be used. The implementation has
1-hour expiry, 5 sessions, and uses MD5 for session IDs.
Parseltongue catches every divergence.
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
            print(f"  {item['name']} = {item.wff} {tag}")
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
    print("Parseltongue — Code-Specification Cross-Validation")
    print("=" * 60)

    # ----------------------------------------------------------
    # Phase 0: Load both documents
    # ----------------------------------------------------------
    print("\n--- Phase 0: Load specification and implementation ---")
    doc_dir = os.path.join(os.path.dirname(__file__), "resources")
    s.load_document("Spec", os.path.join(doc_dir, "spec.txt"))
    s.load_document("Implementation", os.path.join(doc_dir, "implementation.txt"))
    print(f"  Loaded {len(s.documents)} documents")

    # ----------------------------------------------------------
    # Phase 1: Extract facts from the specification
    # ----------------------------------------------------------
    print("\n--- Phase 1: Facts from specification ---")

    load_source(
        s,
        """
        (fact spec-token-expiry 1800
          :evidence (evidence "Spec"
            :quotes ("Default token lifetime MUST be 1800 seconds (30 minutes).")
            :explanation "Specified default token lifetime"))

        (fact spec-max-sessions 3
          :evidence (evidence "Spec"
            :quotes ("Maximum 3 concurrent sessions per user.")
            :explanation "Specified session limit"))

        (fact spec-hash-algorithm "sha256"
          :evidence (evidence "Spec"
            :quotes ("All hashing MUST use SHA-256. MD5 MUST NOT be used anywhere.")
            :explanation "Required hashing algorithm"))

        (fact spec-token-length 64
          :evidence (evidence "Spec"
            :quotes ("Generated tokens MUST be 64 characters (hex-encoded).")
            :explanation "Required token format"))

        (fact spec-md5-forbidden true
          :evidence (evidence "Spec"
            :quotes ("MD5 MUST NOT be used anywhere.")
            :explanation "Security requirement prohibiting MD5"))
    """,
    )

    _print_list(s.list_facts())

    # ----------------------------------------------------------
    # Phase 2: Extract facts from the implementation
    # ----------------------------------------------------------
    print("\n--- Phase 2: Facts from implementation ---")

    load_source(
        s,
        """
        (fact impl-token-expiry 3600
          :evidence (evidence "Implementation"
            :quotes ("TOKEN_EXPIRY = 3600  # seconds")
            :explanation "Actual token expiry in code"))

        (fact impl-max-sessions 5
          :evidence (evidence "Implementation"
            :quotes ("MAX_SESSIONS = 5")
            :explanation "Actual session limit in code"))

        (fact impl-hash-algorithm "sha256"
          :evidence (evidence "Implementation"
            :quotes ("HASH_ALGORITHM = \\"sha256\\"")
            :explanation "Token hashing algorithm in code"))

        (fact impl-session-hash "md5"
          :evidence (evidence "Implementation"
            :quotes ("hashlib.md5(f\\"{user_id}:{now}\\".encode()).hexdigest()")
            :explanation "Session ID generation uses MD5"))

        (fact impl-token-length 64
          :evidence (evidence "Implementation"
            :quotes ("return len(token) == 64  # SHA-256 hex length")
            :explanation "Token validation checks for 64 chars"))
    """,
    )

    _print_list(s.list_facts())

    # ----------------------------------------------------------
    # Phase 3: Cross-validate with diffs
    # ----------------------------------------------------------
    print("\n--- Phase 3: Cross-validation diffs ---")

    load_source(
        s,
        """
        (diff expiry-check
            :replace spec-token-expiry
            :with impl-token-expiry)

        (diff session-limit-check
            :replace spec-max-sessions
            :with impl-max-sessions)

        (diff token-length-check
            :replace spec-token-length
            :with impl-token-length)
    """,
    )

    print("\n  Diff 1 — Token expiry (spec vs impl):")
    print(f"  {s.eval_diff('expiry-check')}")

    print("\n  Diff 2 — Max sessions (spec vs impl):")
    print(f"  {s.eval_diff('session-limit-check')}")

    print("\n  Diff 3 — Token length (spec vs impl):")
    print(f"  {s.eval_diff('token-length-check')}")

    # ----------------------------------------------------------
    # Phase 4: Derive spec violations
    # ----------------------------------------------------------
    print("\n--- Phase 4: Derive spec violations ---")

    load_source(
        s,
        """
        (derive expiry-violates-spec
            (!= impl-token-expiry spec-token-expiry)
            :using (impl-token-expiry spec-token-expiry))

        (derive session-limit-violates-spec
            (!= impl-max-sessions spec-max-sessions)
            :using (impl-max-sessions spec-max-sessions))

        (derive md5-violates-spec
            (and (= impl-session-hash "md5") spec-md5-forbidden)
            :using (impl-session-hash spec-md5-forbidden))

        (derive token-length-matches-spec
            (= impl-token-length spec-token-length)
            :using (impl-token-length spec-token-length))
    """,
    )

    print("  Spec violation theorems:")
    _print_list(s.list_theorems())

    # ----------------------------------------------------------
    # Phase 5: Provenance of a violation
    # ----------------------------------------------------------
    print("\n--- Phase 5: Provenance — why does expiry violate spec? ---")
    print(json.dumps(s.provenance("expiry-violates-spec"), indent=2))

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
    print("Divergences found:")
    print(f"  Token expiry:   spec={s.facts['spec-token-expiry'].wff}s, impl={s.facts['impl-token-expiry'].wff}s")
    print(f"  Max sessions:   spec={s.facts['spec-max-sessions'].wff}, impl={s.facts['impl-max-sessions'].wff}")
    print("  MD5 forbidden:  spec=True, impl uses MD5 for sessions")
    print(f"  Token length:   MATCHES (both {s.facts['spec-token-length'].wff})")
    print(f"\nFinal system: {s}")


if __name__ == "__main__":
    main()
