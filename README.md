<p align="center">
  <img src="https://raw.githubusercontent.com/sci2sci-opensource/parseltongue/HEAD/documentation/resources/parseltongue.svg" alt="Parseltongue" width="200">
</p>

# Parseltongue

A DSL for systems that refuse to speak falsehood.

[![CI](https://github.com/sci2sci-opensource/parseltongue/actions/workflows/ci.yml/badge.svg)](https://github.com/sci2sci-opensource/parseltongue/actions/workflows/ci.yml)
[![Consistency](https://github.com/sci2sci-opensource/parseltongue/actions/workflows/consistency.yml/badge.svg)](https://github.com/sci2sci-opensource/parseltongue/actions/workflows/consistency.yml)
[![Security](https://github.com/sci2sci-opensource/parseltongue/actions/workflows/security.yml/badge.svg)](https://github.com/sci2sci-opensource/parseltongue/actions/workflows/security.yml)
[![Code Stats](https://github.com/sci2sci-opensource/parseltongue/actions/workflows/codestats.yml/badge.svg)](https://github.com/sci2sci-opensource/parseltongue/actions/workflows/codestats.yml)
[![PyPI](https://img.shields.io/pypi/v/parseltongue-dsl)](https://pypi.org/project/parseltongue-dsl/)
[![Python](https://img.shields.io/pypi/pyversions/parseltongue-dsl)](https://pypi.org/project/parseltongue-dsl/)
[![License](https://img.shields.io/github/license/sci2sci-opensource/parseltongue)](https://github.com/sci2sci-opensource/parseltongue/blob/main/LICENSE)

> **03.03 — CLI Tool Beta Released!** Install with `pipx install 'parseltongue-dsl[cli]'`

_Red facts are hallucinated by Claude 4.6 Sonnet:_
![CLI Overview](https://raw.githubusercontent.com/sci2sci-opensource/parseltongue/HEAD/documentation/resources/cli_core_check_halucination.png)

*Explanation: You can see the critique which LLM provided in the markdown document for validation of the `parseltongue.core` module. The problem is that this critique has **no factual basis** and was **hallucinated** by one of the best LLMs on the market, which is shown by **ungrounded facts in red**.*

## Rationale - Why?

LLMs are increasingly used for code review, security auditing, and documentation validation. The problem: they hallucinate. An LLM reviewing an authentication module might flag a "missing bcrypt implementation" that doesn't exist in the code, or miss the actual vulnerability — MD5 used for session IDs — while confidently producing a detailed critique. You get a fluent, plausible security report where some findings are real, some are fabricated, and you have no way to tell which is which without manually verifying every claim.

Parseltongue fixes this by making every claim **provable**. Instead of asking an LLM to produce a prose review, we ask it to encode the codebase as a **formal logic system**. Every extracted fact must cite a verbatim quote from the source code. Every conclusion must derive from stated premises. And every derivation is checked by a symbolic engine that doesn't hallucinate.

This gives you three things that prose reviews cannot:

1. **Hallucination detection.** Every claim traces back to a quote in the source. If the LLM fabricates a security issue — "passwords are hashed using bcrypt" when there's no bcrypt anywhere in the code — the quote verification fails. That failure propagates automatically to every conclusion that depends on it. You don't just catch the fabrication; you see everything it contaminates.

2. **Specification compliance checking.** Load a security spec alongside the implementation. The engine extracts requirements from the spec and facts from the code independently, then cross-validates via `diff` directives. Wrong token expiry values, exceeded session limits, prohibited algorithms in use — every divergence is flagged with full provenance to both documents.

3. **Documentation validation.** Run the engine against a library's README or API docs. Internal contradictions between prose and config tables, unverifiable security audit claims, inconsistencies between documented and actual behavior — all surface automatically with traceable evidence.

![Parseltongue checking itself](https://raw.githubusercontent.com/sci2sci-opensource/parseltongue/HEAD/documentation/resources/cli_self_check.png)

See [Discovered Use Cases](https://github.com/sci2sci-opensource/parseltongue/blob/HEAD/documentation/DISCOVERED-USECASES.md) for more real-world applications.

## Quick Start

We recommend `pipx` for global access. Alternatively, install with `pip` in a virtual environment.

**macOS**
```bash
brew install pipx
pipx install 'parseltongue-dsl[cli]'
```

**Linux (Ubuntu 23.04+ / Debian 12+)**
```bash
sudo apt install pipx
pipx install 'parseltongue-dsl[cli]'
```

**Linux (older)**
```bash
python3 -m pip install --user pipx
pipx install 'parseltongue-dsl[cli]'
```

**Windows**
```powershell
pip install pipx
pipx install "parseltongue-dsl[cli]"
```

**Or with pip directly**
```bash
pip install 'parseltongue-dsl[cli]'
```

**Updating**
```bash
pipx install 'parseltongue-dsl[cli]==0.3.3' --force  # explicit version avoids pip cache issues
```

### Running

```bash
parseltongue
```

This launches the interactive TUI. On first run, a configuration wizard asks for your API endpoint, key, and model. Any OpenAI-compatible endpoint works (OpenRouter, OpenAI, Azure, local servers like vLLM or Ollama).

From the main menu: pick documents, type a question, and the pipeline runs four passes — extraction, blinded derivation, fact-checking, and answer generation. You can review, retry with feedback, or skip each pass interactively.

You can also run directly from the command line:

```bash
parseltongue run \
  -d "auth.py" \
  -d "Spec:api_spec.md" \
  -q "Does the implementation match the specification?" \
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

See the full [CLI documentation](https://github.com/sci2sci-opensource/parseltongue/blob/HEAD/parseltongue/cli/README.md) for TUI navigation, keybindings, screenshots of every screen, and configuration details.

## Python API

The LLM module extends Parseltongue to a neuro-symbolic approach over the symbolic formal reasoning core.

```bash
pip install 'parseltongue-dsl[llm]'
export OPENROUTER_API_KEY=sk-...
```

```python
from parseltongue import System, Pipeline
from parseltongue.llm.openrouter import OpenRouterProvider

system = System(overridable=True)
provider = OpenRouterProvider()

pipeline = Pipeline(system, provider)
pipeline.add_document("Implementation", path="auth.py")
pipeline.add_document("Specification", path="api_spec.md")

result = pipeline.run("Does the implementation match the specification?")
```

- **`result.output.markdown`** — grounded report with `[[type:name]]` references linking every claim to source quotes
- **`result.output.references`** — resolved references: value, provenance chain, and source quotes
- **`result.output.consistency`** — unverified evidence, fabrication chains, diff divergences
- **`result.system`** — the full formal system for inspection via `system.provenance(name)`, `system.eval_diff(name)`, etc.

See the full [LLM pipeline documentation](https://github.com/sci2sci-opensource/parseltongue/blob/HEAD/parseltongue/llm/README.md) for the four-pass architecture, provider interface, extended thinking, and reference resolution.

## Core Engine

The DSL that the pipeline builds under the hood. Five directive types — `fact`, `axiom`, `defterm`, `derive`, `diff` — each grounded in evidence with verbatim quotes. Can be used standalone without any LLM dependency.

```bash
pip install parseltongue-dsl
```

See the full [core documentation](https://github.com/sci2sci-opensource/parseltongue/blob/HEAD/parseltongue/core/README.md) for directive types, evidence grounding, quote verification, custom environments, and consistency checking.

## Project Structure

```
parseltongue/
├── core/                — formal engine: evaluation, evidence, consistency
│   ├── quote_verifier/  — inverted-index quote matching with 6-step normalization
│   ├── demos/           — apples, revenue, biomarkers, code_check, spec_validation, doc_validation
│   └── tests/           — core unit tests (300+)
├── llm/                 — four-pass LLM pipeline: extract → derive → factcheck → answer
│   ├── demos/           — code_check, spec_validation, doc_validation, biomarkers, revenue
│   └── tests/           — llm unit tests (~100)
└── cli/                 — terminal interface: TUI, document ingestion, history
    ├── tui/             — Textual screens, widgets, tree builders
    └── demo/            — sample PDF for testing
```

## Demos

```bash
# Software engineering — no LLM needed
python -m parseltongue.core.demos.code_check.demo        # auth module security audit
python -m parseltongue.core.demos.spec_validation.demo   # auth spec vs implementation
python -m parseltongue.core.demos.doc_validation.demo    # auth library docs validation

# Research & math — no LLM needed
python -m parseltongue.core.demos.biomarkers.demo        # cross-paper scientific conflict
python -m parseltongue.core.demos.revenue_reports.demo   # cross-document analysis
python -m parseltongue.core.demos.apples.demo            # Peano arithmetic from field notes

# LLM pipeline demos — requires API key
python -m parseltongue.llm.demos.code_check.demo         # LLM auth module security audit
python -m parseltongue.llm.demos.spec_validation.demo    # LLM auth spec vs implementation
python -m parseltongue.llm.demos.doc_validation.demo     # LLM auth library docs validation
python -m parseltongue.llm.demos.biomarkers.demo         # LLM biomarker analysis
python -m parseltongue.llm.demos.revenue.demo            # LLM revenue reports

# CLI demo — run the pipeline on the included PDF
parseltongue run -d "parseltongue/cli/demo/nejm.pdf" -q "Find any inconsistencies or red flags."
```
A sample PDF ([`cli/demo/nejm.pdf`](https://github.com/sci2sci-opensource/parseltongue/blob/HEAD/parseltongue/cli/demo/nejm.pdf)) is included for testing the CLI — it's the document used in the screenshots of CLI module.


## Tests

```bash
pip install -e ".[dev,llm]"
pytest                           # all tests
pytest parseltongue/core/tests/  # core only
pytest parseltongue/llm/tests/   # llm only
```

## License

Apache 2.0
