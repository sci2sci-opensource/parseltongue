"""
Demo: Code Implementation Checks

Scenario: Extracting facts from a Python authentication module and
verifying internal consistency. Shows how the system catches both
genuine code properties and fabricated claims about behavior that
doesn't exist in the source.
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

    s = System(overridable=True)
    print("=" * 60)
    print("Parseltongue — Code Implementation Checks")
    print("=" * 60)

    # ----------------------------------------------------------
    # Phase 0: Load source code as a document
    # ----------------------------------------------------------
    print("\n--- Phase 0: Load source code ---")
    doc_dir = os.path.join(os.path.dirname(__file__), "resources")
    s.load_document("auth_module", os.path.join(doc_dir, "auth_module.py.txt"))
    print(f"  Loaded {len(s.documents)} source document(s)")

    # ----------------------------------------------------------
    # Phase 1: Extract verified facts from the code
    # ----------------------------------------------------------
    print("\n--- Phase 1: Extract facts from source code ---")

    load_source(
        s,
        """
        (fact token-expiry 3600
          :evidence (evidence "auth_module"
            :quotes ("TOKEN_EXPIRY = 3600  # seconds")
            :explanation "Default token expiry constant"))

        (fact max-sessions 5
          :evidence (evidence "auth_module"
            :quotes ("MAX_SESSIONS = 5")
            :explanation "Maximum concurrent sessions per user"))

        (fact hash-algorithm "sha256"
          :evidence (evidence "auth_module"
            :quotes ("HASH_ALGORITHM = \\"sha256\\"")
            :explanation "Hashing algorithm used for tokens"))

        (fact token-length 64
          :evidence (evidence "auth_module"
            :quotes ("return len(token) == 64  # SHA-256 hex length")
            :explanation "Expected token length for SHA-256 hex digest"))

        (fact generate-token-returns "hex"
          :evidence (evidence "auth_module"
            :quotes ("A hex-encoded SHA-256 hash token.")
            :explanation "Return type documented in generate_token docstring"))

        (fact session-uses-md5 true
          :evidence (evidence "auth_module"
            :quotes ("hashlib.md5(f\\"{user_id}:{now}\\".encode()).hexdigest()")
            :explanation "Session IDs are generated with MD5"))
    """,
    )

    print(f"  System: {s}")
    _print_list(s.list_facts())

    # ----------------------------------------------------------
    # Phase 2: Derive consistency checks
    # ----------------------------------------------------------
    print("\n--- Phase 2: Internal consistency checks ---")

    load_source(
        s,
        """
        (defterm token-expiry-hours
            (/ token-expiry 3600)
            :evidence (evidence "auth_module"
              :quotes ("Tokens expire after 3600 seconds (1 hour) by default.")
              :explanation "Docstring claims 1 hour, constant is 3600s"))

        (derive expiry-matches-docstring
            (= (/ token-expiry 3600) 1)
            :using (token-expiry))

        (derive sha256-produces-64-hex
            (= token-length 64)
            :using (token-length))
    """,
    )

    print("  Theorems:")
    _print_list(s.list_theorems())

    # ----------------------------------------------------------
    # Phase 3: Fabricated claim — LLM hallucination example
    # ----------------------------------------------------------
    print("\n--- Phase 3: Fabricated claim (simulated LLM hallucination) ---")
    print("  An LLM might claim the module uses bcrypt for password hashing...")

    load_source(
        s,
        """
        (fact uses-bcrypt true
          :evidence (evidence "auth_module"
            :quotes ("passwords are hashed using bcrypt with a cost factor of 12")
            :explanation "Password hashing configuration"))
    """,
    )

    print("  Fact accepted but quote verification fails:")
    _print_list(s.list_facts())

    # ----------------------------------------------------------
    # Phase 4: Fabrication propagation
    # ----------------------------------------------------------
    print("\n--- Phase 4: Fabrication propagation ---")

    load_source(
        s,
        """
        (derive bcrypt-is-secure
            (= uses-bcrypt true)
            :using (uses-bcrypt))
    """,
    )

    print("  Derivation from fabricated source inherits taint:")
    _print_list(s.list_theorems())

    # ----------------------------------------------------------
    # Phase 5: Diff — token vs session hashing consistency
    # ----------------------------------------------------------
    print("\n--- Phase 5: Diff — hashing algorithm consistency ---")
    print("  Tokens use SHA-256 but sessions use MD5. Are they consistent?")

    load_source(
        s,
        """
        (fact session-hash-algorithm "md5"
          :evidence (evidence "auth_module"
            :quotes ("hashlib.md5(f\\"{user_id}:{now}\\".encode()).hexdigest()")
            :explanation "Session ID generation uses MD5"))

        (diff hash-consistency
            :replace hash-algorithm
            :with session-hash-algorithm)
    """,
    )

    print(f"\n  Diff result: {s.eval_diff('hash-consistency')}")

    # ----------------------------------------------------------
    # Phase 6: Provenance trace
    # ----------------------------------------------------------
    print("\n--- Phase 6: Provenance trace ---")
    print("  Tracing expiry-matches-docstring back to source:")
    print(json.dumps(s.provenance("expiry-matches-docstring"), indent=2))

    # ----------------------------------------------------------
    # Phase 7: Consistency report
    # ----------------------------------------------------------
    print("\n--- Phase 7: Consistency report ---")
    report = s.consistency()
    print(f"\n  {report}")

    # ----------------------------------------------------------
    # Summary
    # ----------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"Final system: {s}")
    print("\nVerified facts (grounded in source code):")
    _print_list(s.list_facts())
    print("\nTheorems:")
    _print_list(s.list_theorems())


if __name__ == "__main__":
    main()
