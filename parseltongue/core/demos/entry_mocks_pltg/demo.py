"""
Demo: run-on-entry as a self-contained unit test with let + mocks.

A module rebinds forward-declared primitives (which have no concrete
values) to mock values via let, turning formal expressions into
computable self-tests — only when run as the entry point.
"""

import logging
import os
import sys

from parseltongue import load_main


def pltg_print(_system, *args):
    print(*[str(a).replace("\\n", "\n") for a in args])
    return True


def print_facts(system):
    for name, fact in system.facts.items():
        print(f"  {name} = {fact.wff}")
    return True


def print_theorems(system):
    for t in system.list_theorems():
        print(f"  {t}")
    return True


def assert_true(system, label, value):
    status = "PASS" if value is True else f"FAIL (got {value})"
    print(f"  [{status}] {label}")
    return True


def mock_succ(_system, x):
    return x + 1


EFFECTS = {
    "print": pltg_print,
    "print-facts": print_facts,
    "print-theorems": print_theorems,
    "assert-true": assert_true,
    "mock-succ": mock_succ,
}

if __name__ == "__main__":
    plog = logging.getLogger("parseltongue")
    plog.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("  [%(levelname)s] %(message)s"))
    plog.addHandler(handler)

    os.chdir(os.path.dirname(__file__))

    # Scenario 1: demo.pltg imports math — math's self-test is skipped
    print("=" * 60)
    print("Scenario 1: demo.pltg imports math")
    print("=" * 60)
    load_main("demo.pltg", EFFECTS)

    # Scenario 2: math.pltg as entry point — self-test fires
    print("\n" + "=" * 60)
    print("Scenario 2: math.pltg as entry point (standalone)")
    print("=" * 60)
    os.chdir(os.path.join(os.path.dirname(__file__), "src"))
    load_main("math.pltg", EFFECTS)
    print("=" * 60)
