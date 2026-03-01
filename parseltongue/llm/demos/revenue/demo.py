"""
Demo: LLM four-pass pipeline on revenue reports.

Runs the same revenue analysis as core/demos/revenue_reports — but
instead of hand-crafting the DSL, the LLM extracts facts, builds
derivations, and produces a grounded markdown answer autonomously.

Usage:
    python -m llm.demos.revenue.demo
    python -m llm.demos.revenue.demo --no-thinking
    python -m llm.demos.revenue.demo --reasoning-tokens 8000
"""

import argparse
import json
import logging
import os
import sys

from parseltongue.core import System
from parseltongue.llm import OpenRouterProvider, Pipeline

RESOURCE_DIR = os.path.join(os.path.dirname(__file__), 'resources')


def main():
    parser = argparse.ArgumentParser(description="LLM pipeline demo — revenue reports")
    parser.add_argument('--no-thinking', action='store_true',
                        help='Disable extended thinking')
    parser.add_argument('--reasoning-tokens', type=int, default=None,
                        help='Set explicit reasoning token budget (default: adaptive)')
    parser.add_argument('--model', default='anthropic/claude-sonnet-4.6',
                        help='OpenRouter model ID')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show DEBUG-level pipeline logs')
    args = parser.parse_args()

    # Logging
    log = logging.getLogger('parseltongue')
    log.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('  [%(levelname)s] %(message)s'))
    log.addHandler(handler)

    # Reasoning config
    if args.no_thinking:
        reasoning = None
    elif args.reasoning_tokens:
        reasoning = args.reasoning_tokens
    else:
        reasoning = True  # adaptive thinking

    print("=" * 60)
    print("Parseltongue LLM Pipeline — Revenue Reports")
    print("=" * 60)

    # --- Provider ---
    provider = OpenRouterProvider(model=args.model, reasoning=reasoning)
    print(f"\n  Model: {args.model}")
    print(f"  Thinking: {reasoning}")

    # --- System + Documents ---
    system = System(overridable=True)

    pipeline = Pipeline(system, provider)
    pipeline.add_document("Q3 Report",
                          path=os.path.join(RESOURCE_DIR, "q3_report.txt"))
    pipeline.add_document("FY2024 Targets Memo",
                          path=os.path.join(RESOURCE_DIR, "targets_memo.txt"))
    pipeline.add_document("Bonus Policy Doc",
                          path=os.path.join(RESOURCE_DIR, "bonus_policy.txt"))
    print(f"  Documents: {list(system.documents.keys())}")

    # --- Run ---
    query = "Did the company beat its growth target in Q3? What is the bonus?"
    print(f"\n  Query: {query}")
    print("\n" + "-" * 60)

    result = pipeline.run(query)

    # --- Pass 1 output ---
    print("\n--- Pass 1: Extracted DSL ---")
    print(result.pass1_source)

    # --- Pass 2 output ---
    print("\n--- Pass 2: Derived DSL ---")
    print(result.pass2_source)

    # --- Pass 3 output ---
    print("\n--- Pass 3: Fact Check DSL ---")
    print(result.pass3_source)

    # --- Pass 4 output ---
    print("\n--- Pass 4: Grounded Answer ---")
    print(result.output.markdown)

    # --- Resolved references ---
    print("\n--- Resolved References ---")
    for ref in result.output.references:
        status = f"ERROR: {ref.error}" if ref.error else f"= {ref.value}"
        print(f"  [[{ref.type}:{ref.name}]] {status}")

    # --- System state ---
    print("\n--- Final System State ---")
    print(f"  {system}")
    print(f"  Facts: {list(system.facts.keys())}")
    print(f"  Terms: {list(system.terms.keys())}")
    print(f"  Theorems: {list(system.theorems.keys())}")
    if system.diffs:
        print(f"  Diffs: {list(system.diffs.keys())}")

    # --- Consistency ---
    print("\n--- Consistency ---")
    print(f"  {result.output.consistency}")

    # --- Provenance sample ---
    if system.theorems:
        thm_name = next(iter(system.theorems))
        print(f"\n--- Provenance: {thm_name} ---")
        print(json.dumps(system.provenance(thm_name), indent=2, default=str))


if __name__ == '__main__':
    main()
