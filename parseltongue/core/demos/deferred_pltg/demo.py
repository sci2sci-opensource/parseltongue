"""
Demo: Deferred Directives

Scenario: run-on-entry blocks only fire when a file is the entry point.
A library's deferred block is skipped on import, but executes when loaded
directly — enabling self-tests and setup that don't pollute importers.
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


EFFECTS = {
    "print": pltg_print,
    "print-facts": print_facts,
}

if __name__ == "__main__":
    plog = logging.getLogger("parseltongue")
    plog.setLevel(logging.WARNING)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("  [%(levelname)s] %(message)s"))
    plog.addHandler(handler)

    os.chdir(os.path.dirname(__file__))
    load_main("demo.pltg", EFFECTS)
