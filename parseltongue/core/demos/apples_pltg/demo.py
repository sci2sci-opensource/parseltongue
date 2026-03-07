"""
Demo: Peano Arithmetic via .pltg — Empty-Env Module Loading.

Scenario: Same orchard arithmetic as the apples demo, but executed
entirely through .pltg file loading with an empty initial environment.
Proves that the Loader of modules works correctly to load DSL for
bootstrapping Peano successor notation, axioms, imports, and derives
from scratch — no Python-side setup.
"""

import json
import logging
import os
import sys

from parseltongue import load_main


def provenance(system, name):
    print(json.dumps(system.provenance(str(name)), indent=2))
    return True


def consistency(system):
    report = system.consistency()
    print(f"  {report}")
    return report.consistent


def verify(system, name):
    system.verify_manual(str(name))
    return True


def dump_env(system):
    env = system.engine.env
    print(f"  Environment has {len(env)} entries: {list(env.keys()) if env else '(empty)'}")
    return True


def state(system):
    print(f"  {system}")
    return True


def list_axioms(system):
    for ax in system.list_axioms():
        print(f"  {ax}")
    return True


def list_terms(system):
    for t in system.list_terms():
        print(f"  {t}")
    return True


def list_theorems(system):
    for t in system.list_theorems():
        print(f"  {t}")
    return True


def print_theorem(system, name):
    name = str(name)
    if name in system.theorems:
        print(f"  {system.theorems[name]}")
    return True


def pltg_print(_system, *args):
    print(*[str(a).replace("\\n", "\n") for a in args])
    return True


if __name__ == "__main__":
    plog = logging.getLogger("parseltongue")
    plog.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("  [%(levelname)s] %(message)s"))
    plog.addHandler(handler)

    os.chdir(os.path.dirname(__file__))
    load_main(
        "demo.pltg",
        {
            "dump-env": dump_env,
            "print": pltg_print,
            "provenance": provenance,
            "consistency": consistency,
            "verify": verify,
            "state": state,
            "list-axioms": list_axioms,
            "list-terms": list_terms,
            "list-theorems": list_theorems,
            "print-theorem": print_theorem,
        },
        initial_env={},
        overridable=True,
    )
