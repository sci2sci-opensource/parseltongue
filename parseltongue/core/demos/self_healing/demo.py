"""
Demo: Self-Healing Probes via Effects

The entire flow is written in Parseltongue DSL.  Python only
registers primitive effects and feeds the script.

Effects (the instruction set):
  (load-data name path)          — load a document
  (check-diff name)              — evaluate a diff, true if consistent
  (check-consistency)            — full system consistency report
  (snapshot name)                — save a fact's current value
  (patch-fact name value)        — overwrite a fact
  (rollback name)                — restore a fact from snapshot

The DSL script uses (if (not (check-diff ...)) ...) to
conditionally patch or rollback.

Usage:
    python -m parseltongue.core.demos.self_healing.demo
"""

import logging
import os
import sys

from parseltongue.core import System, load_source
from parseltongue.core.atoms import Evidence

RESOURCE_DIR = os.path.join(os.path.dirname(__file__), "resources")

# ── Primitive Effects ────────────────────────────────────────

_snapshots: dict[str, tuple] = {}


def load_data(system, name, path):
    resolved = os.path.join(RESOURCE_DIR, str(path))
    system.load_document(str(name), resolved)
    print(f"  [load-data] '{name}' ← {path}")
    return True


def check_diff(system, name):
    result = system.eval_diff(str(name))
    print(f"  [check-diff] {result}")
    return not result.values_diverge


def check_consistency(system):
    report = system.consistency()
    print(f"  [consistency] {report}")
    return report.consistent


def snapshot(system, name):
    name = str(name)
    fact = system.facts[name]
    _snapshots[name] = (fact.wff, fact.origin)
    print(f"  [snapshot] Saved {name} = {fact.wff}")
    return True


def patch_fact(system, name, value, document, quote, explanation):
    name, document, quote, explanation = str(name), str(document), str(quote), str(explanation)
    print(f"  [patch-fact] {name} ← {value}")
    evidence = Evidence(document=document, quotes=[quote], explanation=explanation, verify_manual=True)
    system.set_fact(name, value, evidence)
    return True


def rollback(system, name):
    name = str(name)
    value, origin = _snapshots.pop(name)
    system.set_fact(name, value, origin)
    print(f"  [rollback] {name} ← {value} (restored)")
    return True


# ── The Script ───────────────────────────────────────────────

SELF_HEAL_SCRIPT = r"""
; ── Load source ──
(load-data "auth_module" "auth_module.py.txt")

; ── Extract facts ──
(fact hash-algorithm "sha256"
  :evidence (evidence "auth_module"
    :quotes ("HASH_ALGORITHM = \"sha256\"")
    :explanation "Token hashing algorithm"))

(fact session-hash-algorithm "md5"
  :evidence (evidence "auth_module"
    :quotes ("hashlib.md5(f\"{user_id}:{now}\".encode()).hexdigest()")
    :explanation "Session ID uses MD5"))

; ── Detect divergence ──
(diff hash-consistency
    :replace hash-algorithm
    :with session-hash-algorithm)

; ── Initial state ──
(check-consistency)

; ── If divergent: snapshot + patch.  If consistent: rollback. ──
(snapshot "session-hash-algorithm")

(if (not (check-diff "hash-consistency"))
    (patch-fact "session-hash-algorithm" "sha256"
        "auth_module"
        "HASH_ALGORITHM = \"sha256\""
        "Remediation probe: session hash should match token hash")
    (rollback "session-hash-algorithm"))

; ── After patch ──
(check-consistency)

; ── Same conditional again: now consistent → rollback ──
(if (not (check-diff "hash-consistency"))
    (patch-fact "session-hash-algorithm" "sha256"
        "auth_module"
        "HASH_ALGORITHM = \"sha256\""
        "Remediation probe: session hash should match token hash")
    (rollback "session-hash-algorithm"))

; ── Back to original ──
(check-consistency)
"""


def main():
    plog = logging.getLogger("parseltongue")
    plog.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("  [%(levelname)s] %(message)s"))
    plog.addHandler(handler)

    print("=" * 60)
    print("Parseltongue — Self-Healing Probes")
    print("=" * 60)

    s = System(
        overridable=True,
        effects={
            "load-data": load_data,
            "check-diff": check_diff,
            "check-consistency": check_consistency,
            "snapshot": snapshot,
            "patch-fact": patch_fact,
            "rollback": rollback,
        },
    )

    print(s)
    print("\n" + "-" * 60 + "\n")

    load_source(s, SELF_HEAL_SCRIPT)

    print("\n" + "=" * 60)
    print(f"Final: {s}")


if __name__ == "__main__":
    main()
