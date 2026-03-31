# Scope Translation via Morphisms

**Branch**:
**PR**:

## Problem

Bench scopes (lens, screen, hologram, search, ops) are currently hardwired in `BenchSystem`. Cross-scope operations work through ops set operators, but the key spaces are implicit — each scope knows its own forms but there's no formal mechanism to translate between them. The relationships between existing scopes (lens nodes ↔ screen diagnostics ↔ hologram lenses ↔ search hits) are baked into ad-hoc code rather than expressed as composable morphisms. Adding a new scope means modifying `BenchSystem` internals and manually wiring cross-scope logic.

## What we want

A `register_scope` API on the bench:

```python
bench.register_scope("name", system, {
    "lens": SomeLensMorphism(),
    "screen": SomeScreenMorphism(),
})
```

Three arguments: name, system, morphisms.

- **name** — scope identifier, used in `(scope name ...)`
- **system** — a `BenchSubsystem` (tag, operators, posting morphism, ops morphism)
- **morphisms** — dict mapping other scope names to morphisms that translate forms between key spaces

A morphism projects forms from one scope into another's key space, enabling cross-scope set operations via ops without ad-hoc glue. Bidirectional if both sides register morphisms to each other.

## Approach

1. Refactor existing scope registration in `BenchSystem` to use `register_scope` internally — lens, screen, hologram become the first consumers
2. Define the morphism protocol: `project(form) -> key` for key-space translation
3. Wire morphisms into ops so `(scope ops (and-forms (scope A ...) (scope B ...)))` uses the registered A→B morphism automatically when key spaces differ
4. Test with existing systems: define morphisms between all built-in scopes (lens↔screen, lens↔hologram, lens↔search, screen↔search, etc.) — the relationships already exist implicitly, this makes them explicit and composable

## Files likely involved

- `parseltongue/core/inspect/systems/bench_system.py` — `register_scope` API, morphism protocol
- `parseltongue/core/inspect/systems/frozen_bench.py` / `live_bench.py` — use `register_scope` for built-in scopes
- `parseltongue/core/inspect/systems/operations.py` — morphism-aware cross-scope key matching
