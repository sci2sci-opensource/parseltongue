# Compact index — array-backed postings and position maps

**Branch**: `feature/compact-index-arrays`

## Problem

The bench daemon held its corpus index as nested Python containers: one boxed `int` per *character* of every document in two position maps (`position_map`, `collapsed_to_norm`), a `set[int]` of line numbers per (term, document) pair in four separate tables (`word_to_lines`, `stem_to_lines`, and the corpus-level inversions of both), and tuple-keyed bigram/trigram dictionaries per document. Every posting was a heap object; every corpus-level entry repeated the document path as a dict key.

Measured on a multi-repo workspace: a 45 KB source file cost 8 MB of live objects (≈175×). The whole corpus — 42 MB of text — sat at an 18 GB physical footprint, the on-disk caches were 3.7 GB of JSON, cold load took minutes, and the main thread spent essentially all of its CPU inside `_PyGC_Collect` walking the ~100M-object graph on every gen-2 collection. The same functionality in a positional full-text engine (Lucene, Tantivy) costs 0.3–1× raw text.

Two secondary defects surfaced on the way:

- On the mtime-pruned walk path, files re-added from the previous file list skipped `classify_file`, so a `.pgignore` line or size rule added after a file was first indexed never evicted it while its directory mtime stayed put.
- On cache restore, `corpus_words` / `corpus_stems` were materialized as fresh sets instead of sharing the per-document sets the live build shares — the postings existed twice in memory after every daemon restart.

## What we want

The same operator surface — `(scope search …)`, strategies, ranking, quote verification — over structures whose size is proportional to the number of postings at a few bytes each, not to the number of Python objects. Cold load measured in seconds, a cache that is bytes rather than JSON integers, and a heap the cyclic collector does not need to traverse.

## Proposal

One term dictionary per index (`Vocab`: term ↔ 32-bit id, append-only). Every positional structure becomes an `array('I')`:

| Structure | Before | After |
|---|---|---|
| `position_map`, `collapsed_to_norm` | `list[int]`, one per char | `RunMap` — run-length encoded monotone map, two u32 per normalization edit, bisect lookup |
| `word_positions` | `dict[str, list[int]]` | CSR over term ids: sorted ids, offsets, flat positions |
| `word_to_lines`, `stem_to_lines` | `dict[str, set[int]]` | CSR over term ids; `TermLines` mapping view, `LineSet` values with `&`, `|`, `in`, `len` |
| bigrams / trigrams | `dict[tuple, set[int]]` | dropped — `lines_with_phrase` verifies adjacency against the per-line stem sequence (a CSR keyed by line) |
| `corpus_words`, `corpus_stems` | `dict[str, dict[str, set[int]]]` | `CorpusPostings`: CSR term id → doc ids; line detail read from the document; synonym expansion recorded as `syn_sources` and folded in at lookup |
| `stem_df` | `dict[str, int]` | `TermCounts`: u32 array indexed by term id |
| collapsed text | persisted per doc | built lazily on first fallback hit, never persisted |
| `.idx.pgz`, `.six.pgz` | JSON of integers | `BlobPGZ`: JSON head + raw array bytes in one PGZ envelope; load is one `frombytes` per array |

The `.six` cache carries its own term list; on load the ids are re-based onto the live `Vocab` (`remap_csr`), so a cache written against a different dictionary still restores. Corpus-level tables are not persisted — one linear pass over the per-document id arrays rebuilds them faster than they could be read. `System` caches embed the verifier index as base64 blobs inside their JSON.

`gc.freeze()` runs once the corpus is loaded; the pruned walk path now re-classifies every reused entry; `deserialize_search_index` no longer duplicates postings.

### Previous-layout caches are the operator's data

A cache in the pre-blob JSON layout (v1) is never dropped, rewritten, or re-indexed on the daemon's own initiative. At start it is detected by peeking at the payload (`pgz_payload_kind`), streamed into the current in-memory layout one document at a time (`inspect/legacy.py`; the same converter that `pg cache convert` persists), and served like any other cache. While the v1 files are on disk every cache save is held — changes stay searchable in memory, nothing is written under the v1 names. `pg status` shows what was found and the choices; each is an explicit `pg cache <choice>`:

| choice | effect |
|---|---|
| `convert` | write the loaded corpus in the current layout; v1 files moved aside as `*.v1.pgz` (never overwriting an existing backup) |
| `migrate` | convert, then delete the v1 files |
| `rebuild` | v1 files moved aside as `*.v1.pgz`; the recorded directory is re-walked with this version |
| `keep` | nothing; every start streams the v1 files again, saves stay held |

`pg wait` prints the notice right after "Ready.", `pg status` repeats it, and the daemon logs it at the level its default configuration writes. After a convert or rebuild, `pg cache migrate` removes the `*.v1.pgz` backups they left. An unreadable cache (neither layout) is reported and left in place as well. `test_legacy_cache.py` pins all of it: byte-identical cache files after load, queries, a reindex pass and a forced flush; v1 answers equal to a fresh index; documents whose text the history lacks are read from disk, empty files included; each choice's exact effect on disk.

### What may enter a cache that travels

The caches embed every indexed file's full text, so selection is a sharing decision. Two rules were missing: `.pgignore` patterns with a leading `/` are now anchored at the root as in gitignore (`/tmp` previously matched nothing, so a root-level scratch directory was indexed despite being listed), and a file that its own git repository ignores is never indexed — judged by the nearest repository above it (one `git check-ignore --stdin` per repository per walk), so a workspace that ignores its child checkouts at the top level says nothing about the files inside them. Local settings files with credentials were found in a shared cache this way. `test_select_ignore.py` pins both rules, including eviction on the next pass after a rule is added.

### Tokenizer v2 and a pipe-friendly `pg search`

Identifier-like words now yield the sub-tokens people actually type: the units between `/` and `.` (`widgets_v2`, `inference_service`) and, within each, snake/kebab/camelCase parts (`widgets`, `v2`, `asset`, `entry`), with import sigils stripped (`@widgets_v2` → `widgets_v2`). Index and query share `split_compound`, and the camel split reads the original casing through the position map. On the workspace, `grep -w` and `pg` now agree file-for-file on `widgets_v2` (48/48), `inference_service` (3/3), `LLMConfiguration` (16/16), `AssetEntry` (3/3). The `.six` cache carries `tokenizer: 2`; a cache built by another version still loads and `pg wait`/`pg status` say so until `pg reindex --force`, which now re-derives every search document even when no file changed (before, a forced pass re-read files but `DocumentIndex.add` kept unchanged documents, so the tokenizer never took effect).

`pg search` reads its query from an argument, `-f FILE`, `-f -` or a non-tty stdin; prints `path:line:text` when stdout is not a terminal (or `-o grep`), one JSON object per line with `-o json`, and the grouped view with a footer on a terminal. No pagination by default (`-n 0`); `-n N` with `--page/--next/--prev` is explicit. The daemon reply is structured (`lines`, `total`, `offset`, `limit`, `warnings`); the grouped text lines are still supplied as `results` for the TUI.

Measured on the same workspace, v1 caches of 421 MB + 333 MB: start on v1 (streamed) 88–92 s, 1.7 GB; `pg cache convert` 43 s, all 3,232 v1 documents carried over (plus the 2 files that had appeared on disk meanwhile), backups byte-identical to the originals; restart on the converted 96 MB + 112 MB caches 17 s, 1.67 GB, probe queries identical to the v1-served answers.

## Result

On the same workspace (2,800 documents, 42 MB text, previous footprint 18 GB / 3.7 GB of caches):

| | before | after |
|---|---|---|
| process footprint, index loaded | 18 GB | 2.3 GB (≈1.1 GB of it live data: 3.0M-term vocab 330 MB, text + normalized text + lines 355 MB, all posting arrays ≈ 400 MB; the rest is load-time transients malloc keeps) |
| on-disk caches (`.idx` + `.six`) | 753 MB compressed / 3.7 GB JSON | 208 MB, binary |
| cold load from cache | minutes | 10–18 s |
| no-change background reindex pass | 16 s | 3 s (previous file list grouped by directory once per walk; classify verdicts cached per rule configuration) |
| full index from scratch | did not finish on this corpus (quadratic `_normalize_lists`, fixed here) | 145 s |
| objects the GC walks | ~100M | 43 (after `gc.freeze()`); a full gen-2 pass: 0.000 s |
| query latency (`cascade`, 366 hits) | — | 12 ms |

Half the vocabulary (1.4M of 3.0M terms) comes from 98 experiment-result JSON files under 1 MB each; the guardrail and `.pgignore` remain the tool for those — the index now merely makes their cost proportional instead of catastrophic.

Follow-ups, not done here: stream the BlobPGZ read per blob instead of decompressing the whole payload into one buffer (would cut ~0.5 GB from the load peak); a `cost_bytes` per document in `.meta` plus a `pg status` view of the top-N most expensive documents, so the next pathological input is one query away instead of an afternoon of cache forensics.

Test surface: `parseltongue/core/tests/test_compact_index.py` pins RunMap/Vocab/LineSet/CSR/BlobPGZ contracts, the phrase lookup, and the id-rebase round-trip. The legacy inline-search-index migration test was replaced by one asserting the pre-blob cache is dropped cleanly.
