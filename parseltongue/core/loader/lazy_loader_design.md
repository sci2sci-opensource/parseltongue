# LazyLoader Design — How It Must Work

## The Problem

The classic `Loader._load_source` processes directives **sequentially**: parse one, patch it, execute it, move to the next. If any directive fails, the whole file fails. This is correct but fragile — one bad fact kills everything downstream.

`LazyLoader._load_source` must be **fault-tolerant**: parse everything, build a dependency graph, execute in topological order. When a directive fails, only its dependents are skipped — everything else continues.

## The Two Engines

```
LoaderEngine                          Core Engine (inner)
├── evaluate(source, ms) → result     ├── terms, axioms, facts, theorems
├── patch_one(lad, ctx)               ├── execute(expr) → registers definitions
├── delegate_one(lad)                 └── evaluate(expr) → calls effects via env
├── module_aliases
├── names_to_modules
└── names_to_lines
```

- **LoaderEngine** owns namespace state (aliases, name→module mappings) and does patching (namespace definition names, resolve symbols via aliases, patch context keys).
- **Core Engine** owns the registry (terms, axioms, facts, theorems, diffs) and executes directives (register facts, derive theorems, evaluate effects).
- `patch_one` mutates the expression in-place (namespace patching). `delegate_one` passes the patched expression to the core engine for registration.

## What `evaluate()` Returns

`LoaderEngine.evaluate(source, ms)` returns a `LoaderTranslationResult`:
- `result.directives`: list of `LoaderAnnotatedDirective` (LAD), one per parsed expression
- `result.context`: a `PatchContext` for patching

Each LAD contains:
- `directive.sentence.expr` — the parsed S-expression (mutable list, shared by reference)
- `directive.sentence.line` — source line number
- `directive.node.name` — definition name (bare, pre-namespace)
- `is_definition` — True if head is in DSL_KEYWORDS or SPECIAL_FORMS
- `needs_namespace` — True if `not is_main and is_definition`
- `skip_index` — position to protect during symbol patching (usually index 1 = the name)
- `is_main` — whether this is the main module

**Critical**: `evaluate()` is **pure** — it parses and analyzes but does NOT mutate or execute. All expressions are in their original, un-namespaced form. Patching and execution happen later.

## Three Categories of Expressions

Every parsed expression falls into exactly one category:

| Category | Test | Examples | When to execute |
|----------|------|----------|-----------------|
| **Pre-effect** | `head ∈ PRE_DIRECTIVE_EFFECTS` | `import`, `context`, `load-document` | Before directives (phase 1b) |
| **Definition** | `lad.is_definition` | `fact`, `axiom`, `defterm`, `derive`, `diff` | Topological order (phase 4) |
| **Post-effect** | everything else | `verify-manual`, `print`, `consistency`, `run-on-entry` | After all directives (phase 5) |

## The Pipeline — What Each Phase Must Do

### Phase 1a: Parse (pure)

```python
result = self._engine.evaluate(source, local_env=ms)
```

Produces LADs with structural analysis. Collect `defined_names` — the set of names that WILL exist after this module's definitions execute. For non-main modules, these must be the **namespaced** names (e.g. `std.util.export`, not `export`), because `_resolve_bare` constructs `module_name.symbol` and checks against `known_names`.

**No mutations. No execution.**

### Phase 1b: Pre-effects (imports grow the engine)

Execute pre-effects through the engine: `patch_one` + `delegate_one`.

**Critical ordering**: imports must run before definitions because:
1. Imports trigger recursive `_load_source` calls for child modules
2. After import returns, the core engine has the child module's definitions registered
3. Phase 1c's patching needs those definitions in `EngineKnown` to resolve cross-module references

`patch_one` syncs `ctx.aliases` and `ctx.names_to_modules` from the engine on every call. This is essential because imports grow aliases mid-loop (e.g. importing `std` registers alias `counting` → `std.counting`).

### Phase 1c: Patch definitions + build dep graph

Patch ALL definition LADs via `patch_one`. This:
1. Namespaces definition names (`export` → `std.util.export`) via `patch_definition_name`
2. Patches context keys (`(context :file)` → `(context "module.:file")`)
3. Resolves symbols via `_resolve_bare` and `_resolve_dotted`

Symbol resolution needs **two sources** of known names:
- `EngineKnown(inner)` — cross-module names from imports that ran in phase 1b
- `defined_names` — current module's own names (not yet in the engine)

After patching, expressions are mutated in-place. Build `DirectiveNode`s from the patched expressions via `parse_directive`. The nodes extract dependency info (`:using` clauses, symbol references) from the **patched** expressions, so cross-module references are fully qualified.

Then `resolve_graph(nodes)` links nodes into a dependency DAG.

### Phase 4: Topological execution (fault-tolerant)

Walk named nodes in source order. For each node, recursively ensure all dependencies executed first. Then `delegate_one(lad)` — this passes the already-patched expression to the core engine for registration.

On failure: record the error, mark the name as failed, skip all dependents.

**Important**: `delegate_one` does NOT patch — the expression was already patched in phase 1c. It only calls `self._inner.execute(expr)`.

### Phase 5: Post-effects

Execute post-effects through the engine: `patch_one` + `delegate_one`. The engine is now fully populated, so symbol resolution uses `EngineKnown` which sees all registered definitions.

Post-effects like `verify-manual` receive their arguments via the core engine's eval. The arguments (e.g. quoted names) need to be namespace-resolved so they match the registered names.

## Key Invariants

1. **All expressions go through the engine.** Never call `_execute_directive` directly. Always `patch_one` + `delegate_one`. The engine owns namespace state.

2. **`patch_one` before `delegate_one`.** Patching must happen before execution. For definitions, patching is in phase 1c (before dep graph). For effects, patching is inline.

3. **`defined_names` uses namespaced names.** `_resolve_bare` constructs `module.symbol` and checks `known_names`. If `known_names` has bare names, resolution fails.

4. **`ctx` is shared and synced.** `patch_one` syncs `ctx.aliases` and `ctx.names_to_modules` from engine state on every call. This ensures each patch sees the latest aliases (imports grow them).

5. **Expressions are shared by reference.** `lad.directive.sentence.expr` and `node.expr` (from `parse_directive`) point to the same list. Patching one patches both.

6. **Import order matters.** Phase 1b runs imports before phase 1c patches definitions. Child module definitions must be in the engine before parent module symbols can resolve cross-module references.

## Library Modules

### What lib modules are

`lib_paths` is a list of paths to `.pltg` entry files (e.g. `std.pltg`). These are standard-library-level modules that get special treatment: auto-loading, qualified naming, and full alias chains.

### Auto-loading in `load_main`

Before the main file is loaded, `load_main` iterates `lib_paths` and loads each entry file:

```python
for lib_path in self._lib_paths:
    lib_abs = os.path.abspath(lib_path)
    engine.register_lib_module(lib_name)   # mark as lib
    engine.register_module(lib_name)       # register + auto-alias
    # create ModuleContext, push file stack, _load_source(), pop
```

This means by the time the main file's phase 1a runs, all lib entry point definitions are already registered in the core engine. The main file can reference them via aliases.

### Module qualification for lib sub-modules

When a module inside a lib imports a plain (non-dotted) name, `register_module` qualifies it with the parent's name:

```
parent="std", module="higher_order" → "std.higher_order"
```

This only happens when the parent is itself a lib module (`is_lib_module(parent)` is true). The qualified name is also marked as a lib module transitively.

### Alias chains: lib vs project

**Lib modules** get a full alias chain — every suffix of the dotted name becomes an alias:

```
std.higher_order → aliases: higher_order → std.higher_order
std.counting     → aliases: counting → std.counting
```

**Project modules** get only a single short alias (the last component):

```
utils.math → alias: math → utils.math
```

This means `counting.count-exists` resolves via alias `counting` → `std.counting`, then `_resolve_dotted` constructs `std.counting.count-exists` and checks `EngineKnown`.

### How libs interact with LazyLoader phases

1. **Before phase 1a**: `load_main` has already loaded all lib entry files via `_load_source`. Their definitions are in `EngineKnown`. Their aliases are in `engine.module_aliases`.

2. **Phase 1b (imports)**: When the main file does `(import (quote std.counting))`, the import effect:
   - Resolves the module path (checks lib dirs as fallback)
   - Detects if resolved path is under a lib dir → `register_lib_module`
   - Calls `register_module(module_name, parent=current_module)` which may qualify the name
   - Recursively calls `_load_source` for the child module
   - After return, child definitions are in `EngineKnown` and aliases are registered

3. **Phase 1c (patching)**: `patch_one` syncs `ctx.aliases` from `engine.module_aliases` on every call. So lib aliases registered during phase 1b are available for dotted symbol resolution. Cross-module references like `counting.count-exists` resolve through `_resolve_dotted` using these aliases.

4. **Recursive `_load_source`**: When LazyLoader loads an imported module, it runs the full lazy pipeline (phases 1a–5) for that module. The child module's definitions get registered in the core engine during its phase 4. When the parent's phase 1b import returns, those definitions are visible via `EngineKnown`.

### The `_path_to_module` guard

Before loading a module file, the import effect checks `_path_to_module` — a map from absolute path to module name. If the path was already loaded (possibly under a different name), it calls `register_or_alias` instead of re-loading. This handles diamond imports (A imports B and C, both import D).

### Relative imports are never lib

If a module name starts with `.` (e.g. `.sibling`, `..std.counting`), it is a **relative import** — resolved via filesystem path from the current directory. Leading dots are stripped by `parse_module_name` and used for directory traversal.

Relative imports are **never** treated as lib modules, regardless of where they resolve. Even if a relative import happens to resolve to a file inside a lib directory, the module is loaded as a normal project module (no lib qualification, no full alias chain). This is by design — the `.` prefix means "I know where this file is relative to me."

However, loading a lib module via a relative round-trip is still a **valid import**. If `..std.counting` resolves to the same absolute path as `std.counting` (already loaded), the `_path_to_module` guard catches it and registers an alias rather than re-loading. The module keeps its original lib identity.

### `resolve_module_path` fallback

Module resolution first checks the computed relative path. If the file doesn't exist there, it falls back to searching `lib_dirs` (derived from `lib_paths`). This allows `(import (quote counting))` to find `std/counting.pltg` in the lib directory even without a relative path match.

## What Goes Wrong When Invariants Break

| Broken invariant | Symptom |
|-----------------|---------|
| `_execute_directive` bypasses engine | Cross-module names unresolved (`engine.export-X`) |
| `defined_names` has bare names | `_resolve_bare` can't find `module.symbol` → unresolved symbols |
| Patching after dep graph | `resolve_graph` sees unpatched names → wrong dependencies |
| Effects not patched | `verify-manual` checks bare name, fact registered under namespaced name |
| Imports run after patching | `EngineKnown` empty during patching → cross-module resolution fails |
| `ctx` not synced | Stale aliases → alias-based resolution fails for later imports |
