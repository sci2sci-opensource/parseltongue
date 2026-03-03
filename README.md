<p align="center">
  <img src="https://raw.githubusercontent.com/sci2sci-opensource/parseltongue/HEAD/parseltongue.svg" alt="Parseltongue" width="200">
</p>

# Parseltongue

A DSL for systems that refuse to speak falsehood.

[![CI](https://github.com/sci2sci-opensource/parseltongue/actions/workflows/ci.yml/badge.svg)](https://github.com/sci2sci-opensource/parseltongue/actions/workflows/ci.yml)
[![Security](https://github.com/sci2sci-opensource/parseltongue/actions/workflows/security.yml/badge.svg)](https://github.com/sci2sci-opensource/parseltongue/actions/workflows/security.yml)
[![PyPI](https://img.shields.io/pypi/v/parseltongue-dsl)](https://pypi.org/project/parseltongue-dsl/)
[![Python](https://img.shields.io/pypi/pyversions/parseltongue-dsl)](https://pypi.org/project/parseltongue-dsl/)
[![License](https://img.shields.io/github/license/sci2sci-opensource/parseltongue)](https://github.com/sci2sci-opensource/parseltongue/blob/main/LICENSE)

> **03.03 — CLI Tool Beta Released!** Install with `pip install parseltongue-dsl[cli]`

_Red facts are hallucinated by Claude 4.6 Sonnet:_
![CLI Overview](https://raw.githubusercontent.com/sci2sci-opensource/parseltongue/HEAD/cli_core_check_halucination.png)



## Rationale - Why?

LLMs hallucinate. They produce fluent, confident text that may have no basis in the source material. Traditional approaches treat this as a retrieval problem — feed the model better context and hope for the best. But even with perfect retrieval, nothing stops the model from inventing facts, misquoting sources, or drawing conclusions that don't follow from the evidence.

Parseltongue takes a different approach: instead of asking an LLM to summarize documents, we ask it to encode each of the documents as a **logic system**. Every extracted fact must cite a verbatim quote. Every conclusion must derive from stated premises. And every derivation is checked.

This gives us two things that prose summaries cannot:

1. **Hallucination detection.** Every claim traces back to a quote in a source document. If the LLM fabricates a fact, the quote verification fails — and that failure propagates automatically to every conclusion that depends on it. You don't just catch the lie; you see everything it contaminates. This also gives the user the ability to verify only the foundation — the basic facts — conclusions are guaranteed to follow from them.

2. **Cross-document consistency checking.** Speaking plainly — **we validate if the ground truth is trustable itself.** The formal system makes it possible to compute the same value via independent paths — say, a reported growth percentage vs. one calculated from absolute revenue figures in a different document. When these paths disagree, the system flags a divergence. This catches not only LLM errors, but genuine inconsistencies in the source documents.

The result is a system where the LLM does what it's good at (reading documents, identifying relevant facts, understanding relationships) while the formal engine does what LLMs are bad at (tracking provenance, checking logical consistency, propagating uncertainty). 

And of course it's perfect for documentation or checking code.

![Parseltongue checking itself](https://raw.githubusercontent.com/sci2sci-opensource/parseltongue/HEAD/cli_self_check.png)

## Quick Start

```bash
pip install parseltongue-dsl[cli]
parseltongue
```

This launches the interactive TUI. On first run, a configuration wizard asks for your API endpoint, key, and model. Any OpenAI-compatible endpoint works (OpenRouter, OpenAI, Azure, local servers like vLLM or Ollama).

From the main menu: pick documents, type a question, and the pipeline runs four passes — extraction, blinded derivation, fact-checking, and answer generation. You can review, retry with feedback, or skip each pass interactively.

You can also run directly from the command line:

```bash
parseltongue run \
  -d "Q3 Report:q3_report.pdf" \
  -d "Targets:targets_memo.txt" \
  -q "Did we beat the growth target?" \
  --model anthropic/claude-sonnet-4.6
```

| Command | Description |
|---|---|
| `parseltongue` | Launch the interactive TUI |
| `parseltongue run -d ... -q ...` | Run pipeline directly on documents |
| `parseltongue inspect file.pdf` | Preview document conversion |
| `parseltongue history` | Browse past runs |
| `parseltongue configure` | Re-run the configuration wizard |

Supports PDF, DOCX, PPTX, XLSX, HTML (via [Docling](https://ds4sd.github.io/docling/)), plus all plain text and code formats.

See the full [CLI documentation](parseltongue/cli/README.md) for TUI navigation, keybindings, screenshots of every screen, and configuration details.

## Python API

```bash
pip install parseltongue-dsl[llm]
export OPENROUTER_API_KEY=sk-...
```

```python
from parseltongue import System, Pipeline
from parseltongue.llm.openrouter import OpenRouterProvider

system = System(overridable=True)
provider = OpenRouterProvider()

pipeline = Pipeline(system, provider)
pipeline.add_document("Q3 Report", path="q3_report.pdf")
pipeline.add_document("Targets Memo", path="targets_memo.txt")

result = pipeline.run("Did we beat the growth target? What is the bonus?")
```

- **`result.output.markdown`** — grounded report with `[[type:name]]` references linking every claim to source quotes
- **`result.output.references`** — resolved references: value, provenance chain, and source quotes
- **`result.output.consistency`** — unverified evidence, fabrication chains, diff divergences
- **`result.system`** — the full formal system for inspection via `system.provenance(name)`, `system.eval_diff(name)`, etc.

See the full [LLM pipeline documentation](parseltongue/llm/README.md) for the four-pass architecture, provider interface, extended thinking, and reference resolution.

## Core Engine

The DSL that the pipeline builds under the hood. Five directive types — `fact`, `axiom`, `defterm`, `derive`, `diff` — each grounded in evidence with verbatim quotes. Can be used standalone without any LLM dependency.

```bash
pip install parseltongue-dsl
```

See the full [core documentation](parseltongue/core/README.md) for directive types, evidence grounding, quote verification, custom environments, and consistency checking.

## Project Structure

```
parseltongue/
├── core/                — formal engine: evaluation, evidence, consistency
│   ├── quote_verifier/  — inverted-index quote matching with 6-step normalization
│   ├── demos/           — apples (Peano arithmetic), revenue, biomarkers
│   └── tests/           — core unit tests (300+)
├── llm/                 — four-pass LLM pipeline: extract → derive → factcheck → answer
│   ├── demos/           — end-to-end revenue demo
│   └── tests/           — llm unit tests (~100)
└── cli/                 — terminal interface: TUI, document ingestion, history
    ├── tui/             — Textual screens, widgets, tree builders
    └── demo/            — sample PDF for testing
```

## Demos

```bash
# Core demos — no LLM needed
python -m parseltongue.core.demos.apples.demo
python -m parseltongue.core.demos.revenue_reports.demo
python -m parseltongue.core.demos.biomarkers.demo

# LLM pipeline demo
python -m parseltongue.llm.demos.revenue.demo

# CLI demo — run the pipeline on the included PDF
parseltongue run -d "parseltongue/cli/demo/nejm.pdf" -q "Find any inconsistencies or red flags."
```
A sample PDF ([`cli/demo/nejm.pdf`](parseltongue/cli/demo/nejm.pdf)) is included for testing the CLI — it's the document used in the screenshots above.


## Tests

```bash
pip install -e ".[dev,llm]"
pytest                           # all tests
pytest parseltongue/core/tests/  # core only
pytest parseltongue/llm/tests/   # llm only
```

## License

Apache 2.0
