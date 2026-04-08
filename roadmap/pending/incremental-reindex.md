# Incremental reindex — only re-walk what's actually changed

## Problem

`pg index .` and `pg index . --force` are the only two modes for refreshing the search index, and both walk the entire tree of every previously-indexed directory every time. For the small single-repo case this is fine — a full walk is sub-second and the merkle/stat cache skips re-reading unchanged files. For the workspaces parseltongue was just opened up to (orchestrated multi-repo, deeply nested layouts, hundreds of thousands of files), the full re-walk itself becomes the bottleneck:

- **Without `--force`**: pg index has to `stat` every tracked file to know whether it's changed. The hash check is fast, but the stat fan-out is what dominates wall time on large trees. On a workspace with ~2300 indexed files spread across a dozen child repos, re-running `pg index .` after a single small file change still takes seconds, and the cost grows linearly with the indexed set, not with the actual change set.
- **With `--force`**: every file is re-read regardless. Tens of MB of disk reads to refresh after a one-line edit. This is the right behavior for "the schema or extraction logic changed, redo everything," but it's wildly excessive for the common case of "I just edited one file, please notice."
- **No mode for "I know what changed"**: there's no way to say "reindex only `OSS/parseltongue/temp/foo.md`" or "reindex everything modified in the last 5 minutes." The user has the information; the tool refuses to use it.

The cumulative effect: in interactive workflows where the user wants the index to track their edits in near-real-time (the dream use case for an inspection daemon), they end up either re-running `pg index .` every few minutes and eating the latency, or running it less often and querying stale data. Neither is what an "always live" bench should look like.

## What we want

One or more of the following modes — they're complementary, not exclusive:

1. **Targeted reindex by path**: `pg reindex <path> [<path>...]` — re-stat and re-read only the named files (or recursively, only the named directories). The user supplies the change set; pg trusts them and skips the rest of the tree entirely.

2. **Time-windowed reindex**: `pg reindex --since <duration-or-timestamp>` — walk only files whose mtime is within the window. Implemented as a top-level filter on the tree walk (`os.walk` + per-entry stat already happens; just add a time predicate). Cheap and useful.

3. **Watch mode**: `pg watch` — long-running file-system watcher (inotify on linux, FSEvents on mac, ReadDirectoryChangesW on windows; the `notify` Python crate or equivalent abstracts these). Subscribes to the indexed directories; on each event, re-index just the affected file. Daemon-side, so the index stays fresh without user effort. This is the "always live" version.

4. **Diff against the cache**: even without an explicit user signal, pg can do better than a full walk. The merkle/stat cache knows what it last saw; the directories themselves know their mtime; if a directory's mtime hasn't moved since the last index pass, the contents haven't changed and the walk can short-circuit at the directory level. This is a pure optimization of the existing `pg index` path — no API change — but it makes the no-flag mode usable on big trees.

(4) is the most impactful for the broad case. (1) and (2) are escape hatches for interactive workflows where the user knows exactly what changed. (3) is the long-term destination where reindex stops being something the user thinks about at all.

## Files likely involved

- `parseltongue/core/inspect/store.py` (or wherever `index_incremental` and `reindex` live in the search store) — add the directory-mtime short-circuit and the targeted-reindex API.
- `parseltongue/core/inspect/bench_cli.py` — new `pg reindex` subcommand with `--path`, `--since`, etc. flags. Possibly a new `pg watch` subcommand if (3) lands.
- `parseltongue/core/inspect/search.py` view layer — surface the new entrypoints to the daemon's RPC interface so they're callable from the CLI client.
- A small benchmark or property test to pin the expected speedup on a synthetic 10k-file tree.

## Notes

This task is the natural follow-on to [decouple-pgignore-from-gitignore](decouple-pgignore-from-gitignore.md). That one fixed *what* gets indexed in a multi-repo workspace; this one fixes *how often* and *how cheaply* the index gets refreshed once it's in place. Together they make the bench actually pleasant to use in the orchestrated-workspace case it was just opened up to.

A subtle precondition: the merkle/stat cache itself has to be correct under the new modes. If a targeted reindex of `foo.md` updates the per-file cache entry, that's fine. If the directory-mtime shortcut skips a subtree whose mtime is stale (because git checkout updated files without bumping the dir mtime, on filesystems where that can happen), the index silently desyncs from disk. Worth thinking through the corner cases — and probably worth a `pg index . --verify` mode that diffs the index against a fresh full walk and reports drift, as a safety valve when the user suspects the incremental path got it wrong.
