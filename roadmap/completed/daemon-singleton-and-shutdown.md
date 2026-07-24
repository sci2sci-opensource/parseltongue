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

## Result

**Branch**: feature/daemon-singleton-and-shutdown

All five wants landed, plus a `pg stop` command that fell out of the replace machinery.

**Singleton (`bench_cli.py`)**
- `_probe_daemon(sock_path)` — connect + ping with a 2s timeout. Distinguishes live daemon / stale socket file / no socket.
- `serve`, `start`, and `up` all run `_ensure_socket_free()` first: live daemon → refuse with pid, pltg path, and the three ways out (`pg reload`, `pg stop`, `--replace`); stale socket file → removed automatically; free → proceed.
- `--replace` (new flag on all three start variants) sends the daemon a `shutdown` action over its own socket (falls back to SIGTERM via the advertised pid for daemons that don't speak it), then waits up to 15s for both the socket release and process exit before starting.
- `_run_server` no longer unconditionally steals the socket path — the historical mechanism by which N daemons stacked up. A second daemon now refuses at bind time even if the CLI guard was bypassed.
- New `shutdown` dispatch action: acks over the socket first, then SIGTERMs itself (works mid-load too).
- New `pg stop [--socket]` command: clean shutdown + wait for release, and stale-socket cleanup when nothing is listening.

**Process name**
- `_daemonize` now execs `python -m parseltongue.core.inspect.bench_cli serve <pltg> ...` in the grandchild. The daemon's argv is honest: `ps` shows what it is, and `pkill -f bench_cli` matches, as the docs always claimed.

**Bounded shutdown (`pgz.py`, `store.py`)**
- Root cause of the multi-GB shutdown balloon: `json_pgz_write` one-shot `json.dumps(...).encode()` + `zlib.compress` — three full copies of the index in RAM, inside C calls that hold the GIL, so the SIGTERM handler couldn't even run until the save finished.
- `json_pgz_write` now streams: chunked `iterencode` → sha256/zlib fed incrementally → file, header back-patched. Peak memory is the 1 MB buffer, not the payload; the GIL is released between chunks so SIGTERM stays answerable mid-save.
- `ordinal_pgz_write` compresses per-entry — the uncompressed text block is never materialized. On-disk formats unchanged (existing roundtrip tests pass untouched).
- All pgz writes land via `.tmp` + rename — a kill mid-save can no longer tear the cache file; the previous valid cache survives a failed save.
- The >4 GiB envelope limit (uint32 size field) now fails fast with a clear message instead of a post-hoc `struct.error`; the running total aborts the save the moment it crosses the line.
- `store.save` / `save_diagnosis` routed through the streaming writer.
- `_cleanup` itself: SIGALRM 10s hard backstop, registry deregistration, then `os._exit(0)` — no interpreter finalization over a multi-GB live index.

**Visibility**
- Daemons register in `~/.parseltongue/daemons.json` (sock, pid, pltg, cwd, started) on bind and deregister on clean shutdown.
- `pg status --all` lists every registered daemon with liveness state (`pong`/`loading`/`unresponsive`) and prunes entries whose process is gone.
- `ping` and `status` responses now carry pid + pltg path (this is also what powers the refuse message and `--replace` fallback).

**Docs**
- Kung-fu learning path: cleanup recipe rewritten around `pg stop` / `pg start --replace` / `pg status --all`; manual `rm` of stale sockets documented as no longer needed.
- data_governance demo README: `pkill -f pg-bench; sleep 1` → `pg-bench stop`.
- Lifecycle help on serve/start/up and the top-level command listings updated.

**Tests**: `test_daemon_lifecycle.py` — 16 tests covering probe (absent/stale/live), singleton refusal message, stale-socket removal, `--replace` termination, socket-level terminate with dead-pid cleanup, shutdown action ack-before-signal ordering, ping pid/pltg advertisement, registry roundtrip/replacement/corruption tolerance, and pid liveness.

**Deferred (follow-on entries if picked up)**
- uint64 PGZ envelope (`PGZ\x02` magic, backward-compatible reads) if >4 GiB single payloads become real.
- `pg watch` / inotify-driven reindex belongs to the incremental-reindex task, but the singleton guard is its prerequisite and is now in place.
