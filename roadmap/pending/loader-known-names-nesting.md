# Loader Known Names Nest per Directive — Large Modules Overflow the Stack

## Problem

`LoaderEngine.patch_one` (`parseltongue/core/loader/loader_engine.py`) is
called once per directive of a module, all against the module's one
`PatchContext`, and each call with the same `extra_names` set (the
`LazyLoader` passes the module's collected names). Every call wraps the
context's known names again:

```python
ctx.known_names = _UnionKnown(ctx.known_names, extra_names)
```

so after `n` directives the known names are `n` nested unions, and a name
lookup (`_resolve_bare`: `candidate in ctx.known_names`) recurses `n` levels
through `_UnionKnown.__contains__`. A module of a few thousand directives
that resolve a symbol (any fact with an `:evidence` form does) overflows the
stack: on Python 3.12 near 5,000 levels (the C stack), on any Python past the
recursion limit the engine raises (10,000). The import fails with "maximum
recursion depth exceeded", none of the module's definitions load, and
everything that rests on them is skipped as a dependency failure, with no
hint that size was the cause.

Generated modules hit this first: a catalog of a few thousand records written
out as facts is an ordinary input. Lookups are also quadratic in the module's
length before they overflow (a 6,000-directive module loads ~10× slower than
it should).

## What we want

- The known names wrapped once per context: a module's directives share the
  context and the names, so a union already holding these names as its outer
  layer is not wrapped again.
- A regression test: a module with more directives than the stack holds
  (12,000, past the engine's raised limit on any Python), each resolving a
  symbol, imports with all its definitions.

## Approach

Done on `feature/loader-known-names-nesting`, not yet released:

```python
already = isinstance(ctx.known_names, _UnionKnown) and ctx.known_names._b is extra_names
if extra_names is not None and not already:
    ctx.known_names = _UnionKnown(ctx.known_names, extra_names)
```

with `test_an_imported_module_longer_than_the_stack_loads` in
`parseltongue/core/tests/test_lazy_loader.py` (fails before the change with a
stack overflow, passes after). The bug dates from the core refactor that
introduced `_UnionKnown`; every release since carries it, so it ships in the
next patch release.

## Files likely involved

`parseltongue/core/loader/loader_engine.py`,
`parseltongue/core/tests/test_lazy_loader.py`.
