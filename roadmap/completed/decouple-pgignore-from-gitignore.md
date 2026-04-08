# Decouple .pgignore / language detection from .gitignore

**Branch**: `feature/decouple-pgignore-from-gitignore`

## Problem

`.pgignore` and `pg.toml` generation are hard-coupled to `.gitignore`. There is no way to opt out — the generator unconditionally absorbs `.gitignore` patterns into `.pgignore` and unconditionally uses them to prune the language-detection walk. This produces wrong output in any workspace where `.gitignore` does not represent "files I don't care about indexing".

The general principle the current behavior violates: **"git tracks" and "I want this in my searchable index" are different questions.** Pretending they're the same makes the tool wrong for any workspace where they diverge:

- **Orchestrated multi-repo workspaces** (xen, vcstool, google-repo, mr, gita, etc.). The parent `.gitignore` deliberately hides every child placement so the parent's git stays unaware of them. Absorbing those entries into `.pgignore` makes the indexer skip the entire project.
- **Monorepos with build artifacts you actually want indexed** — generated docs, vendored sources kept in-tree but ignored, schema dumps, lockfiles you want searchable.
- **Research / data projects** where `data/` is gitignored for size but is exactly what you want to grep.
- **The inverse** — directories git tracks but you don't want indexed (`fixtures/`, large `testdata/` corpora). Absorbing `.gitignore` doesn't help you here either; the coupling solves only one half of the problem.

A second, related defect compounds the first: `detect_languages()` has a **hardwired shallow walk depth** (default 2) and is not exposed by `pg init`. Any project where source lives more than two directories below the chosen root — common in monorepos and multi-repo workspaces — gets wrong language detection on init, because the walk only sees top-level files at the deepest level it visits. The result is a `pg.toml` with the wrong extension list, and the indexer subsequently skips files it would otherwise have read. Even if the user manually edits `.pgignore` to undo the gitignore absorption, the wrong extensions in `pg.toml` still degrade the index.

The two defects amplify each other: a multi-repo or deeply nested workspace gets hit by both the gitignore absorption (every nested directory pruned) AND the depth limit (the walker can't reach into them anyway). The user's only signal that anything is wrong is a suspiciously low file count from `pg index`, with no warning, no diagnostic, and no hint that the defaults made an unsafe assumption about workspace shape.

## What we want

`.gitignore` absorption and walk depth should be **default preferences, not hardwired rules**. Specifically:

1. **A flag / config switch to opt out of `.gitignore` absorption**, applied to *both* `.pgignore` generation and language-detection pruning. The two are separate features and should both honor the switch.
2. **`pg init` CLI surface** for the switch — `pg init --no-gitignore` (or equivalent), and a persistable `[init]` section in `pg.toml` (e.g. `absorb_gitignore = false`) so subsequent regens don't quietly re-absorb.
3. **Detection and ignore-file generation should not silently share a data source.** They happen to today; that's an implementation accident. Either should be configurable independently of the other.
4. **Walk depth should not be hardwired.** Either pick a much deeper default (e.g. 6) with the existing prune set doing the work of skipping noisy dirs, or replace the walk-based detection with a different strategy entirely — e.g. recursively locate every `pyproject.toml`/`Cargo.toml`/`package.json`/`go.mod`/etc. and use the *presence* of those as language signals. They're cheap to find, located at repo roots, and far more reliable than extension sampling.
5. **Expose `--depth` on `pg init`** as an escape hatch for unusual layouts, even if the default changes.
6. **Detection should be additive across `pg index` calls.** If a user runs `pg index path/A` and later `pg index path/B`, the second call should *grow* the language set in `pg.toml` to include languages found in B — not silently leave them out. The index is already additive across paths; detection should follow.
7. **Loud signal when the workspace looks unusual.** If `.gitignore` lists more than N entries that look like nested git repos (e.g. presence of `<entry>/.git`), pg should warn at init time: "absorbed N gitignore entries that look like nested git repositories — if this is an orchestrated multi-repo workspace, rerun with `--no-gitignore`." Silent degradation is the worst failure mode here; users had no signal anything was wrong other than a suspiciously low indexed-file count.

## Proposal

- `config.generate_pgignore(directory, *, absorb_gitignore: bool = True)` — add the kwarg, default preserves current behavior.
- `config.detect_languages(directory, depth=…, *, use_gitignore_prune: bool = True)` — same shape; raise the default depth and/or replace the strategy.
- `config.generate_pg_toml(directory, *, use_gitignore_prune: bool = True)` — thread the kwarg.
- `config.init(...)` grows an `absorb_gitignore` parameter that flips both behaviors atomically.
- The `pg init` CLI grows a `--no-gitignore` flag (and ideally a `--depth` flag for the walk-based path).
- The setting written to `pg.toml` should be sticky across re-inits with `--append` mode.
- Add the "looks like a multi-repo workspace" heuristic warning at the end of `init()`. Cheap implementation: count `.git/` dirs under the absorbed entries.
- Document in the kung-fu learning path: "if your workspace uses an orchestrator like xen / vcstool / google-repo / mr, or your source lives more than 2 directories below the workspace root, pass `--no-gitignore` (and verify the detected language list) on first init."

## Files likely involved

- `parseltongue/core/inspect/config.py` — `generate_pgignore`, `detect_languages`, `generate_pg_toml`, `init`, `_read_gitignore`
- `parseltongue/core/inspect/bench_cli.py` — `init_config` command
- A small demo / test fixture exercising the multi-repo / deep-nesting case
- The kung-fu learning path docs

## Result

Both root-cause defects (gitignore coupling AND shallow walk depth) are addressed in a single coherent change. The behavior is opt-out via a single CLI flag.

**`parseltongue/core/inspect/config.py`:**
- `generate_pgignore(directory, *, absorb_gitignore: bool = True)` — added kwarg. When `False`, the `# From .gitignore` block is omitted entirely from the generated `.pgignore`.
- `detect_languages(directory, depth: int = 6, *, use_gitignore_prune: bool = True)` — depth raised from 2 to 6 (covers most nested workspace layouts), prune-set absorption is now opt-out via the kwarg. The hardcoded floor (`node_modules`, `__pycache__`, `vendor`, `target`, `.git`) still applies regardless.
- `generate_pg_toml(directory, *, use_gitignore_prune: bool = True)` — threaded the kwarg through to `detect_languages`.
- `init(directory, toml_mode, pgignore_mode, *, absorb_gitignore: bool = True)` — single switch flips both behaviors atomically. Returns `absorb_gitignore` in the result dict for downstream display.

**`parseltongue/core/inspect/bench_cli.py`:**
- `pg init` grows `--no-gitignore` flag with a clear help string explaining the orchestrated-multi-repo use case (xen / vcstool / google-repo).
- The result line includes `absorb_gitignore: false (--no-gitignore)` when the flag is used so users can confirm the path they expected got taken.

**Verification (end-to-end against a real xen workspace):**
- Before: detection found `json, parseltongue, shell, toml` (4 languages); `pg index .` reported "278 files indexed" on a workspace with hundreds of thousands of files.
- After (with `--no-gitignore`): detection found `astro, css, csv, html, javascript, jinja, json, latex, lua, parseltongue, python, sass, shell, terraform, toml, typescript, xml, yaml` (18 languages); `pg index . --force` indexed 2290 files. The same workspace went from broken to fully searchable in one flag.

**Deferred to future work (not in this PR):**
- The "looks like a multi-repo workspace" heuristic warning at init time (still worth adding — silent degradation remains the worst failure mode).
- A persistable `[init] absorb_gitignore = false` key in `pg.toml` so subsequent `pg init --append` runs don't silently re-absorb.
- `--depth` CLI flag on `pg init` for the walk-based detection path.
- Detection additivity across multiple `pg index` calls (currently each call re-detects from scratch from the indexed root; running `pg index path/A` then `pg index path/B` does not grow the language set in `pg.toml`).
- The alternative detection strategy (recursively locate `pyproject.toml`/`Cargo.toml`/`package.json`/`go.mod` and use their presence as language signals).
- Documentation in the kung-fu learning path covering the orchestrated-workspace caveat.

These should be tracked as follow-on roadmap entries when picked up.

## Notes

The current behavior is documented in `config.py` docstrings as "absorbs `.gitignore`" — so it's intentional, not a bug in the narrow sense. This task reframes both defects: gitignore absorption and the shallow walk depth are sensible *defaults* for the common case (single repo with a hand-curated `.gitignore`, source at the top level). But they must be defeatable, the user must be able to know they were applied, and the tool should not silently produce a degraded index when its assumptions are wrong. **Silent degradation on init is the worst failure mode** — the user gets a "N files indexed" success message and no signal that the assumed shape mismatched their actual project.
