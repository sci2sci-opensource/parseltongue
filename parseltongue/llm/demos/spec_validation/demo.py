"""
Demo: LLM four-pass pipeline on code-specification cross-validation.

Runs the same spec-vs-implementation analysis as core/demos/spec_validation —
but instead of hand-crafting the DSL, the LLM extracts facts, builds
derivations, and produces a grounded markdown answer autonomously.

Usage:
    python -m parseltongue.llm.demos.spec_validation.demo
    python -m parseltongue.llm.demos.spec_validation.demo --no-thinking
    python -m parseltongue.llm.demos.spec_validation.demo --reasoning-tokens 8000
"""

import argparse
import logging
import os
import sys

from parseltongue.core import System
from parseltongue.llm import Pipeline
from parseltongue.llm.demos._output import print_result
from parseltongue.llm.openrouter import OpenRouterProvider

RESOURCE_DIR = os.path.join(os.path.dirname(__file__), "resources")


def main():
    parser = argparse.ArgumentParser(description="LLM pipeline demo — code-specification cross-validation")
    parser.add_argument("--no-thinking", action="store_true", help="Disable extended thinking")
    parser.add_argument(
        "--reasoning-tokens", type=int, default=None, help="Set explicit reasoning token budget (default: adaptive)"
    )
    parser.add_argument("--model", default="anthropic/claude-sonnet-4.6", help="OpenRouter model ID")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show DEBUG-level pipeline logs")
    args = parser.parse_args()

    # Logging
    log = logging.getLogger("parseltongue")
    log.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("  [%(levelname)s] %(message)s"))
    log.addHandler(handler)

    # Reasoning config
    if args.no_thinking:
        reasoning = None
    elif args.reasoning_tokens:
        reasoning = args.reasoning_tokens
    else:
        reasoning = True  # adaptive thinking

    print("=" * 60)
    print("Parseltongue LLM Pipeline — Code-Specification Cross-Validation")
    print("=" * 60)

    provider = OpenRouterProvider(model=args.model, reasoning=reasoning)
    print(f"\n  Model: {args.model}")
    print(f"  Thinking: {reasoning}")

    system = System(overridable=True)

    pipeline = Pipeline(system, provider)
    pipeline.add_document("Spec", path=os.path.join(RESOURCE_DIR, "spec.txt"))
    pipeline.add_document("Implementation", path=os.path.join(RESOURCE_DIR, "implementation.txt"))
    print(f"  Documents: {list(system.documents.keys())}")

    query = "Does the implementation match the specification? Find all divergences."
    print(f"\n  Query: {query}")
    print("\n" + "-" * 60)

    result = pipeline.run(query)

    print_result("Parseltongue LLM Pipeline — Code-Specification Cross-Validation", result, system)


if __name__ == "__main__":
    main()
