"""Shared markdown output for LLM demos."""

import json


def print_result(title, result, system):
    """Print pipeline result as markdown."""
    print(f"# {title}\n")

    print(f"**Model:** `{result.model if hasattr(result, 'model') else 'N/A'}`\n")

    print("## Pass 1: Extracted DSL\n")
    print("```lisp")
    print(result.pass1_source)
    print("```\n")

    print("## Pass 2: Derived DSL\n")
    print("```lisp")
    print(result.pass2_source)
    print("```\n")

    print("## Pass 3: Fact Check DSL\n")
    print("```lisp")
    print(result.pass3_source)
    print("```\n")

    print("## Pass 4: Grounded Answer\n")
    print(result.output.markdown)
    print()

    print("## Resolved References\n")
    for ref in result.output.references:
        status = f"ERROR: {ref.error}" if ref.error else f"= {ref.value}"
        print(f"- `[[{ref.type}:{ref.name}]]` {status}")
    print()

    print("## Final System State\n")
    print(f"- **System:** {system}")
    print(f"- **Facts:** {', '.join(f'`{k}`' for k in system.facts.keys())}")
    if system.terms:
        print(f"- **Terms:** {', '.join(f'`{k}`' for k in system.terms.keys())}")
    if system.theorems:
        print(f"- **Theorems:** {', '.join(f'`{k}`' for k in system.theorems.keys())}")
    if system.diffs:
        print(f"- **Diffs:** {', '.join(f'`{k}`' for k in system.diffs.keys())}")
    print()

    print("## Consistency\n")
    print(f"{result.output.consistency}\n")

    if system.theorems:
        thm_name = next(iter(system.theorems))
        print(f"## Provenance: `{thm_name}`\n")
        print("```json")
        print(json.dumps(system.provenance(thm_name), indent=2, default=str))
        print("```")
