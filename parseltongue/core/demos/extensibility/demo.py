"""
Demo: System Extensibility — Effects

Scenario: Instead of loading documents from Python, we pass a
`load-data` effect at construction time.  The DSL itself calls
(load-data "name" "path") as a top-level directive, which hits
the catch-all `else` branch in _execute_directive and evaluates
the expression — executing the side effect.

Effects are callables that receive (system, *args).  The system
auto-wraps them so the DSL sees a plain operator.

Usage:
    python -m parseltongue.core.demos.extensibility.demo
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


RESOURCE_DIR = os.path.join(os.path.dirname(__file__), "resources")


def load_data(system, name, path):
    """Effect: load a document into the system from the resources dir."""
    resolved = os.path.join(RESOURCE_DIR, str(path))
    system.load_document(str(name), resolved)
    print(f"  [load-data] Loaded '{name}' from {resolved}")
    return True


def main():
    plog = logging.getLogger("parseltongue")
    plog.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("  [%(levelname)s] %(message)s"))
    plog.addHandler(handler)

    print("=" * 60)
    print("Parseltongue — Extensibility: Effects")
    print("=" * 60)

    # ----------------------------------------------------------
    # Step 1: Create system with a `load-data` effect
    # ----------------------------------------------------------
    print("\n--- Step 1: System with load-data effect ---")

    s = System(overridable=True, effects={"load-data": load_data})
    print("  Registered effect: (load-data name path)")

    # ----------------------------------------------------------
    # Step 2: DSL loads documents via the custom operator
    # ----------------------------------------------------------
    print("\n--- Step 2: DSL loads documents (side effects!) ---")
    print("  The DSL itself triggers file loading — no Python calls needed.")

    load_source(
        s,
        """
        (load-data "auth_module" "auth_module.py.txt")
    """,
    )

    print(f"  Documents in system: {list(s.documents.keys())}")

    # ----------------------------------------------------------
    # Step 3: Now extract facts — same DSL, same session
    # ----------------------------------------------------------
    print("\n--- Step 3: Extract facts from loaded document ---")

    load_source(
        s,
        """
        (fact token-expiry 3600
          :evidence (evidence "auth_module"
            :quotes ("TOKEN_EXPIRY = 3600  # seconds")
            :explanation "Default token expiry constant"))

        (fact hash-algorithm "sha256"
          :evidence (evidence "auth_module"
            :quotes ("HASH_ALGORITHM = \\"sha256\\"")
            :explanation "Hashing algorithm used for tokens"))

        (fact session-uses-md5 true
          :evidence (evidence "auth_module"
            :quotes ("hashlib.md5(f\\"{user_id}:{now}\\".encode()).hexdigest()")
            :explanation "Session IDs are generated with MD5"))
    """,
    )

    print(f"  System: {s}")
    _print_list(s.list_facts())

    # ----------------------------------------------------------
    # Step 4: Derive and verify — business as usual
    # ----------------------------------------------------------
    print("\n--- Step 4: Derive security checks ---")

    load_source(
        s,
        """
        (derive expiry-is-one-hour
            (= (/ token-expiry 3600) 1)
            :using (token-expiry))

        (fact session-hash-algorithm "md5"
          :evidence (evidence "auth_module"
            :quotes ("hashlib.md5(f\\"{user_id}:{now}\\".encode()).hexdigest()")
            :explanation "Session ID generation uses MD5"))

        (diff hash-consistency
            :replace hash-algorithm
            :with session-hash-algorithm)
    """,
    )

    print("  Theorems:")
    _print_list(s.list_theorems())
    print(f"\n  Diff hash-consistency: {s.eval_diff('hash-consistency')}")

    # ----------------------------------------------------------
    # Step 5: Provenance & consistency
    # ----------------------------------------------------------
    print("\n--- Step 5: Provenance & consistency ---")
    print(json.dumps(s.provenance("expiry-is-one-hour"), indent=2))
    print(f"\n  {s.consistency()}")

    # ----------------------------------------------------------
    # Summary
    # ----------------------------------------------------------
    print("\n" + "=" * 60)
    print("Key takeaway: the system loaded its own documents via DSL.")
    print("Any callable in env can be a top-level directive.")
    print(f"\nFinal system: {s}")


if __name__ == "__main__":
    main()
