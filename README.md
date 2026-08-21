<p align="center">
  <img src="https://raw.githubusercontent.com/sci2sci-opensource/parseltongue/HEAD/documentation/resources/parseltongue-icon.svg" alt="Parseltongue" width="200">
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

> **v0.7.0 — Seeing the Sentences.** Interactive visualization, search engine with provenance, stack-based evaluator, pgmd notebooks. Install with `pip install 'parseltongue-dsl'` or start with [documentation](https://sci2sci-opensource.github.io/parseltongue/index.html).

**Notebook example for this repo:**

![Engine self-inspection notebook](https://raw.githubusercontent.com/sci2sci-opensource/parseltongue/HEAD/documentation/resources/engine_self_notebook.png)
_The engine inspects itself — a pgmd notebook with inline computed values, taint propagation, and derivation paths_

**Materialized knowledge graph of this notebook:**

![Engine graph overview](https://raw.githubusercontent.com/sci2sci-opensource/parseltongue/HEAD/documentation/resources/engine_overview.png)
_2000+ nodes rendered as an interactive graph — zoom, click any node for full evidence and derivation tree_

[Explore the engine demo live →](https://sci2sci-opensource.github.io/parseltongue/demos/engine_overview_core_overview.html)

## Repository self-validation

The repository validates both its public README claims and the curated `parseltongue.core` proof estate. The top-level `parseltongue.pltg` imports those two independent validation layers and finishes with `(consistency :raise)`, so unverified evidence or a divergent cross-check makes the command fail:

```bash
python -m parseltongue load_main parseltongue.pltg
```

The required Consistency workflow runs that self-validation entry point and the whole-estate consistency tests on every pull request and push to `main` or `master`. The tests enforce grounded evidence, true theorems, and no dangling definitions; confounded diff evidence is tracked separately as explicit validation debt until every diff has independent support on both sides.

## Rationale - Why?

LLMs are increasingly used for code review, security auditing, and documentation validation. The problem: they hallucinate. An LLM reviewing an authentication module might flag a "missing bcrypt implementation" that doesn't exist in the code, or miss the actual vulnerability — MD5 used for session IDs — while confidently producing a detailed critique. You get a fluent, plausible security report where some findings are real, some are fabricated, and you have no way to tell which is which without manually verifying every claim.

Parseltongue fixes this by making every claim **provable**. Instead of asking an LLM to produce a prose review, we ask it to encode the codebase as a **formal logic system**. Every extracted fact must cite a verbatim quote from the source code. Every conclusion must derive from stated premises. And every derivation is checked by a symbolic engine that doesn't hallucinate.

This gives you three things that prose reviews cannot:

1. **Hallucination detection.** Every claim traces back to a quote in the source. If the LLM fabricates a security issue — "passwords are hashed using bcrypt" when there's no bcrypt anywhere in the code — the quote verification fails. That failure propagates automatically to every conclusion that depends on it. You don't just catch the fabrication; you see everything it contaminates.

2. **Specification compliance checking.** Load a security spec alongside the implementation. The engine extracts requirements from the spec and facts from the code independently, then cross-validates via `diff` directives. Wrong token expiry values, exceeded session limits, prohibited algorithms in use — every divergence is flagged with full provenance to both documents.

3. **Documentation validation.** Run the engine against a library's README or API docs. Internal contradictions between prose and config tables, unverifiable security audit claims, inconsistencies between documented and actual behavior — all surface automatically with traceable evidence.

A few examples of what it looks like for this repository:

![Engine layers and derivation](https://raw.githubusercontent.com/sci2sci-opensource/parseltongue/HEAD/documentation/resources/engine_focused_subgraph.png)
_Focused subgraph with layers view — depth-based layout showing the full dependency structure_

![Derivation layers](https://raw.githubusercontent.com/sci2sci-opensource/parseltongue/HEAD/documentation/resources/engine_derivation_layers.png)
_Derivation layers — every theorem traces back to source-quoted facts_


See [Discovered Use Cases](https://github.com/sci2sci-opensource/parseltongue/blob/HEAD/documentation/DISCOVERED-USECASES.md) for more real-world applications and experiment with them [in live demos.](https://sci2sci-opensource.github.io/parseltongue/demos.html)


## Quick Start

> For a guided walkthrough, see the [Quick Start page](https://sci2sci-opensource.github.io/parseltongue/quickstart.html).

### Agentic Quick Start

Parseltongue is designed to work with LLM coding agents. Paste this prompt into Claude Code, Cursor, or any agent with terminal access:

> Run `pip install parseltongue-dsl` to install the Parseltongue formal reasoning library. It gives you a CLI called `pg`.
> Run `pg learn --help` to see available learning paths, then run `pg learn <name>` for each one listed and read the full output carefully — these are your operational guides for working with Parseltongue.
> Once you've read them, tell me what you can now do and ask me what I'd like to work on.

The agent installs, reads the learning scripts (`kung-fu` for bench mastery, `to-connect` for pgmd notebooks), and starts a conversation about what to do next. It now knows how to start the bench daemon, index files, search with provenance, screen for consistency, and generate interactive visualizations.

[Quick Start page](https://sci2sci-opensource.github.io/parseltongue/quickstart.html) page contains instructions for Web UI agents, manual setup, and follow-up prompts.

### Install Full Package

Install the full package with TUI, Docling document conversion, and standalone LLM verification pipelines. We recommend `pipx` for global access. Alternatively, install with `pip` in a virtual environment.

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
pipx install 'parseltongue-dsl[cli]==0.7.0' --force  # explicit version avoids pip cache issues
```

### Running

The package installs two entry points:

**`parseltongue`** — interactive TUI and LLM verification pipeline. On first run, a configuration wizard asks for your API endpoint, key, and model. Any OpenAI-compatible endpoint works (OpenRouter, OpenAI, Azure, local servers like vLLM or Ollama). From the main menu: pick documents, type a question, and the pipeline runs four passes — extraction, blinded derivation, fact-checking, and answer generation. You can review, retry with feedback, or skip each pass interactively.

```bash
parseltongue                         # launch TUI
parseltongue run \                   # or run directly
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

**`pg`** (alias `pg-bench`) — persistent workbench daemon. Loads a `.pltg` formal system into memory, indexes source documents, and serves queries over a Unix socket. Includes a full-text search engine with ngrams, stemming, BM25, and RRF ranking; structural lenses for graph navigation; consistency screening with issue/warning/dangling classification; holograms for side-by-side comparison of diff sides; time-travel history with checkpoint layers and non-destructive restore; and interactive HTML visualization with D3 graph, cards, and layers views.

```bash
pg start main.pltg --user "Alice" --assistant "Claude"
pg wait                                # block until ready
parseltongue bench                     # connect from TUI — everything in one screen
pg screen                              # consistency report
pg find "engine"                       # structural search across pltg nodes
pg search '(in "auth.py" "raise")'     # full-text with S-expression query language
pg eval '(scope hologram (dissect "my-diff"))'  # side-by-side diff comparison
pg history layers                      # checkpoint history
pg eval '(fmt "viz" (scope lens (find ".*")))' > viz.html  # interactive visualization
```

Run `pg learn --help` to see built-in learning scripts that cover the full system.

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

## Demos

15 demos ship with the library — 10 core (no LLM needed) and 5 LLM pipeline demos. [Browse the live rendered demos →](https://sci2sci-opensource.github.io/parseltongue/demos.html)

```bash
# Software engineering — no LLM needed
python -m parseltongue.core.demos.code_check.demo        # auth module security audit
python -m parseltongue.core.demos.spec_validation.demo   # auth spec vs implementation
python -m parseltongue.core.demos.doc_validation.demo    # auth library docs validation

# Research & math — no LLM needed
python -m parseltongue.core.demos.biomarkers.demo        # cross-paper scientific conflict
python -m parseltongue.core.demos.revenue_reports.demo   # cross-document analysis
python -m parseltongue.core.demos.apples.demo            # Peano arithmetic from field notes
python -m parseltongue.core.demos.apples_pltg.demo       # same in pure .pltg with splat axioms
python -m parseltongue.core.demos.apples_splats_pltg.demo  # variadic splat patterns

# Governance & architecture — no LLM needed
python -m parseltongue.core.demos.data_governance_pltg.demo  # five-layer compliance analysis
python -m parseltongue.core.demos.engine_overview.demo       # engine self-inspection pgmd notebook

# LLM pipeline demos — requires API key
python -m parseltongue.llm.demos.code_check.demo         # LLM auth module security audit
python -m parseltongue.llm.demos.spec_validation.demo    # LLM auth spec vs implementation
python -m parseltongue.llm.demos.doc_validation.demo     # LLM auth library docs validation
python -m parseltongue.llm.demos.biomarkers.demo         # LLM biomarker analysis
python -m parseltongue.llm.demos.revenue.demo            # LLM revenue reports

# CLI demo — run the pipeline on the included PDF
parseltongue run -d "parseltongue/cli/demo/nejm.pdf" -q "Find any inconsistencies or red flags."
```


## Tests

```bash
pip install -e ".[dev,llm]"
pytest                           # all tests
pytest parseltongue/core/tests/  # core only
pytest parseltongue/llm/tests/   # llm only
```

## License

Apache 2.0
