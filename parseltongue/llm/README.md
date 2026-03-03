# Parseltongue LLM Pipeline

The four-pass pipeline that turns documents + a question into a grounded, cross-validated answer. Built on the [core engine](../core/README.md).

## Quick Start

```bash
pip install parseltongue-dsl[llm]
export OPENROUTER_API_KEY=sk-...
```

Give it documents and a question — the pipeline builds a formal logic system, cross-validates it, and returns a grounded answer where every claim links back to a verbatim quote:

```python
from parseltongue import System, Pipeline
from parseltongue.llm.openrouter import OpenRouterProvider


system = System(overridable=True)
# overridable=True lets statements overwrite each other (useful for LLM pipelines
# that may revise facts across passes). Default is False — statements are immutable
# and must be explicitly retracted before redefining.
provider = OpenRouterProvider()  # reads OPENROUTER_API_KEY from .env

pipeline = Pipeline(system, provider)
pipeline.add_document("Q3 Report", path="q3_report.txt")
pipeline.add_document("Targets Memo", path="targets_memo.txt")
pipeline.add_document("Bonus Policy", text="Bonus is 20% of base salary...")

result = pipeline.run("Did we beat the growth target? What is the bonus?")
```

See the [full demo output](demos/revenue/demo_example_output.md) for a complete example.

### What You Get Back

- **`result.output.markdown`** — a human-readable report where every claim is tagged with `[[type:name]]` references to the formal system. Each reference resolves to a full JSON tree: the derivation chain, the verbatim source quotes, and how trustworthy the claim is (verified, unverified, or fabrication). If the documents contradict each other, the report opens with a warning.
- **`result.output.references`** — the resolved references as a list: each tag mapped to its value, provenance chain, and source quotes.
- **`result.output.consistency`** — a consistency report listing unverified evidence, fabrication chains, and diff divergences.
- **`result.system`** — the full formal system the LLM built, available for further inspection via `system.provenance(name)`, `system.eval_diff(name)`, etc.

For example, `result.output.markdown` might contain:

```markdown
> **Inconsistency detected:** The reported growth of 15% does not match
> the 9.52% computed from absolute revenue figures [[diff:growth-check]].
```

The `[[diff:growth-check]]` reference resolves to a `DiffResult`:

```
name:        growth-check
replace:     revenue-q3-growth
with:        revenue-growth-from-absolutes
value_a:     15
value_b:     9.523809523809524
divergences:
  beat-target:   [True, False]
  bonus-amount:  [30000.0, 0]
```

The diff tells you not just that two values disagree, but exactly which downstream conclusions flip as a result — here, whether the target was beaten and whether a $30,000 bonus is paid.

You can drill into the full provenance via `system.provenance("growth-check")`:

```json
{
  "name": "growth-check",
  "type": "diff",
  "replace": "revenue-q3-growth",
  "with": "revenue-growth-from-absolutes",
  "value_a": 15,
  "value_b": 9.52,
  "divergences": {
    "beat-target": [true, false],
    "bonus-amount": [30000.0, 0]
  },
  "provenance_a": {
    "name": "revenue-q3-growth",
    "type": "fact",
    "origin": {
      "document": "Q3 Report",
      "quotes": ["up 15% year-over-year"],
      "verified": true,
      "grounded": true
    }
  },
  "provenance_b (simplified)": {
    "name": "revenue-growth-from-absolutes",
    "type": "term",
    "definition": "(* (/ (- revenue-q3-abs revenue-q2) revenue-q2) 100)",
    "origin": {
      "document": "Targets Memo",
      "quotes": ["Q2 FY2024 actual revenue was $210M.", "Q3 FY2024 actual revenue was $230M."],
      "verified": true,
      "grounded": true
    }
  }
}
```

Each side traces back to its source: one to a verified quote in the Q3 Report, the other to a formula over audited figures from the Targets Memo.

## Four-Pass Pipeline

Each pass uses LLM tool calling (`tool_choice="required"`) so the model outputs structured DSL, never raw prose.

```
  Documents + Query
        |
  Pass 1: Extract -----> facts, axioms, terms with :evidence
        |
  Pass 2: Derive ------> derivations and diffs (values HIDDEN)
        |
  Pass 3: Fact-Check ---> cross-validation via alternative paths + diffs
        |
  Pass 4: Answer -------> grounded markdown with [[type:name]] references
```

| Pass | Tool | Input | Output |
|---|---|---|---|
| **1. Extract** | `extract` | Full documents + query | Facts, axioms, terms with `:evidence` |
| **2. Derive** | `derive` | **Blinded** system state (names and types, no values) + query | Derivations and diffs |
| **3. Fact-Check** | `factcheck` | Full system state (all values visible) + query | Alternative computation paths, each ending in a `(diff ...)` |
| **4. Answer** | `answer` | Full system state + query | Grounded markdown with `[[type:name]]` references |

Pass 2 is **blinded** to fact values, forcing the LLM to reason about structure rather than guess numbers. Pass 3 sees everything and cross-validates — every verification angle must end with a diff so the engine can detect divergences mechanically.

## Provider Interface

The pipeline is backend-agnostic. Implement `LLMProvider.complete()` to use any model:

```python
from parseltongue.llm import LLMProvider

class MyProvider(LLMProvider):
    def complete(self, messages: list[dict], tools: list[dict], **kwargs) -> dict:
        # Send messages + tools, force a tool call, return parsed arguments
        # Must return e.g. {"dsl_output": "..."} or {"markdown": "..."}
        ...
```

The default `OpenRouterProvider` supports extended thinking:

```python
provider = OpenRouterProvider(model="anthropic/claude-sonnet-4.6")
provider = OpenRouterProvider(model="anthropic/claude-sonnet-4.6", reasoning=True)     # adaptive
provider = OpenRouterProvider(model="anthropic/claude-sonnet-4.6", reasoning=8000)     # explicit budget
```

## Reference Resolution

Pass 4 markdown contains `[[type:name]]` tags. The resolver maps each to the formal system:

- `[[fact:revenue-q3]]` — evaluates the fact's value
- `[[term:bonus-amount]]` — evaluates the term's definition
- `[[axiom:add-commutative]]` — the axiom's WFF as s-expression
- `[[theorem:target-exceeded]]` — the theorem's WFF + derivation sources
- `[[quote:revenue-q3]]` — full provenance chain back to source document
- `[[diff:growth-check]]` — diff result with divergences (if any)

## Key Files

| File | Purpose |
|---|---|
| `pipeline.py` | Orchestrates the 4 passes |
| `provider.py` | `LLMProvider` ABC |
| `openrouter.py` | `OpenRouterProvider` (OpenAI-compatible) |
| `tools.py` | Tool schemas for each pass |
| `prompts.py` | Prompt builders (system + user messages) |
| `dsl_reference.py` | Formats system state for prompts (blinded vs full) |
| `resolve.py` | `[[type:name]]` tag resolution |

## Demo

```bash
python -m parseltongue.llm.demos.revenue.demo
python -m parseltongue.llm.demos.revenue.demo --reasoning-tokens 8000
python -m parseltongue.llm.demos.revenue.demo --no-thinking
```

## Running Tests

```bash
pytest parseltongue/llm/tests/ -v
```
