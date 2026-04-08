# Daemon singleton + clean shutdown

## Problem

`pg start <pltg>` is supposed to be the single-daemon entrypoint — there should be at most one bench daemon for any given pltg, and re-running `pg start` should either refuse, reuse the existing daemon, or replace it cleanly. In practice, none of those happen:

1. **`pg start` does not detect an existing daemon.** Each invocation double-forks a fresh Python process, with no liveness check on the existing socket holder. A user (or an agent) running `pg start ./main.pltg` repeatedly during a session ends up with N parallel daemons, each holding the same indexed pltg in memory, each polling for the same socket, each booked into the same logbook. This was observed in a real session: three concurrent `pg start ./main.pltg` daemons accumulated by the end of the day, each consuming ~99% of one CPU and growing memory continuously.

2. **`pkill -f 'pg-bench|bench_cli'` does not catch them.** The actual process name on disk is `python /Users/.../bin/pg start ./main.pltg ...` — the `bench_cli` token only appears in module imports, not in the visible argv. Documentation in the kung-fu learning path tells users to `pkill -f bench_cli` for cleanup, which is technically wrong on the current install layout. The recommended cleanup command leaves the rogue daemons running.

3. **SIGTERM hangs in the shutdown handler.** When the rogue daemons were finally identified (via `ps aux | grep 'pg start'`) and sent SIGTERM, two of three entered uninterruptible-sleep (`U`) state and **grew memory from a few MB to multiple gigabytes** during shutdown — presumably because the cleanup handler tries to serialize the in-memory index to disk and never completes. After 5+ seconds of waiting, the only recovery was `kill -9` followed by manual socket removal.

The compounding effect: a slow leak silently piles up daemons over a long session, the documented cleanup command fails, the signal-based clean shutdown actively makes things worse during termination, and the user has to fall back to the exact `kill -9` path the docs warn against.

## What we want

Each piece is independently addressable and they compose naturally:

1. **`pg start` should be a singleton** for a given socket / pltg combination. On invocation, check `~/.parseltongue/bench.sock` (or wherever the canonical socket lives). If a live daemon is already serving it:
   - Default: refuse with a clear message ("daemon already running for ./main.pltg, PID 12345 — use `pg reload` to refresh, `pg purge --yes` to nuke and restart, or `pg start --replace` to terminate and respawn").
   - With `--replace` (or `--force`): SIGTERM the existing daemon, wait for socket release, then spawn the new one.
   - Liveness check: try to connect to the socket and issue a no-op ping; if the socket is stale (no listener), clean it up and proceed without erroring.

2. **`pg-bench` should set its argv0 / process name** so `pkill -f bench_cli` actually matches it. Either via `setproctitle` (if available) or by ensuring the daemonized child execs with a recognizable command name. This is a one-line fix in `daemonize()` and makes the documented cleanup command actually work.

3. **The shutdown handler must not balloon memory.** Whatever the SIGTERM path is doing — flushing the merkle cache, persisting the search index, writing the final logbook entry — it should be bounded in memory and should complete within a reasonable timeout (say, 10 seconds) or yield to a `kill -9`. The current behavior of "consume 3 GB while shutting down" is worse than just exiting with a possibly-stale on-disk index. Profile the shutdown path; the most likely culprit is materializing the entire posting set into a list before serializing, which is fine for small corpora and catastrophic for large ones.

4. **`pg status` should report all known daemons**, not just "the one that responded on the socket I tried first." Useful for users debugging exactly the situation above. `pg status --all` could enumerate `~/.parseltongue/*.sock` and ping each.

5. **The kung-fu learning path docs need updating** once (1)–(4) land. The current "pkill -f bench_cli, rm the stale socket" recipe is the wrong hammer for the wrong nail; the right one is `pg start --replace` (or equivalent) once it exists.

## Files likely involved

- `parseltongue/core/inspect/bench_cli.py` — `start` / `up` / `serve` subcommands; daemonization. Add the singleton check and the `--replace` flag here.
- `parseltongue/core/inspect/store.py` (or wherever the bench server's signal handler / shutdown logic lives) — bound the shutdown memory and timeout.
- The daemonization code path itself — set the child's process name so `pkill -f bench_cli` matches.
- The kung-fu learning path content — update cleanup recipes after the new flags land.

## Notes

This task is the next step after [decouple-pgignore-from-gitignore](decouple-pgignore-from-gitignore.md) and [incremental-reindex](incremental-reindex.md): together they make the bench *useful* in large workspaces; this task makes it *robust* under sustained interactive use. A long agent session that opens and closes the bench many times currently leaks daemons silently; a singleton check makes that impossible by construction.

Lower-priority but worth flagging in the same area: the logbook accumulates one entry per `pg start` invocation. With the leak above, sessions accumulate dozens of duplicate logbook rows pointing at the same user/assistant pair. After (1) lands the duplication stops on its own, but a one-shot cleanup utility (`pg logbook compact` or similar) might be useful for projects that already have a polluted logbook.
