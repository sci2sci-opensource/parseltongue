# PGF — Parseltongue Formation

## Problem

Parseltongue projects grow into full applications with multiple subsystems: search engines, consistency checkers, lenses, hologram comparisons, custom scopes, renderers. Bench itself is one such system — but it's hand-wired in Python. There's no declarative way to describe "I want a system with these subsystems, these scopes, these data sources, wired together like this."

Research projects (e.g. vstar-bc) also grow into app-like structures: workstreams, source documents, pgmd annotations, fact modules, axiom libraries, analysis layers, rendered output. No manifest, no packaging, no way to declare the assembly.

## What we want

A declarative format — `.pgf` (Parseltongue Formation) — inspired by Terraform's HCL. Describes the assembly of parseltongue systems:

1. **Project structure**: declare workstreams, resources, modules, outputs, and dependencies. Single entry point for loading a whole project.

2. **System formation**: declaratively compose pg subsystems — scopes, engines, indices, renderers, effects — into a running system. Bench is one formation. A user could define their own formation with different subsystems, custom scopes, different data pipelines.

## Terraform parallels

| Terraform | PGF |
|-----------|-----|
| resource blocks | subsystems, scopes, data sources |
| modules | importable pg packages with inputs/outputs |
| providers | subsystem types (search, lens, screen, hologram, custom) |
| state file | formation cache |
| `plan` | consistency check (declared vs actual) |
| `apply` | instantiate and wire the formation |
| outputs | exported interfaces for other formations |

## Example

```hcl
formation "vstar-bench" {
  version = "0.1"

  engine "core" {
    entry = "analysis/workstreams.pltg"
    documents = "resources/clean/*.txt"
  }

  subsystem "search" {
    type  = "search"
    index = "."
    extensions = [".py", ".pltg", ".pgmd", ".txt"]
  }

  subsystem "lens" {
    type   = "lens"
    source = engine.core
  }

  subsystem "screen" {
    type   = "consistency"
    source = engine.core
  }

  scope "ops" {
    type = "operations"
  }

  workstream "kinetics" {
    sources  = "resources/clean/jones_2023.txt"
    annotate = "workstream_a/jones.pgmd"
    facts    = "workstream_a/jones_facts.pltg"
  }

  workstream "variance" {
    sources  = "resources/clean/gullo_2022.txt"
    annotate = "workstream_b/gullo.pgmd"
    facts    = "workstream_b/gullo_facts.pltg"
  }

  output "html" {
    renderer = "viz"
    path     = "pgmd_out"
  }
}
```

## Key design points

- Formations describe how to wire pg subsystems together, not the subsystem internals
- Subsystem types are pluggable — bench's built-ins (search, lens, screen, hologram) plus user-defined
- Inline pltg expressions where needed — values can be S-expressions evaluated at formation time, e.g. `filter = (scope lens (kind "fact"))` or `entry = (project workstream-entry)`
- Dependency graph is explicit: subsystems reference each other, formation resolves wiring order
- Workstreams are independent — can be loaded in parallel
- Formation cache tracks declared vs actual state
- Packaging: bundle pgf + referenced files + cache into a distributable archive
- `pg formation plan` shows what needs to change, `pg formation apply` instantiates it

## Status

TODO — design phase. Needs format spec, parser, subsystem registry, formation runtime.
