"""
Demo: run-on-entry — deferred directives that only fire for the main file.

Shows that a library's run-on-entry block is skipped when imported,
but executes when the library is loaded as the entry point.
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
    plog.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("  [%(levelname)s] %(message)s"))
    plog.addHandler(handler)

    os.chdir(os.path.dirname(__file__))
    load_main("demo.pltg", EFFECTS)
