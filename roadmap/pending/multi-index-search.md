# Multi-Index Search

## Problem

`pg-bench index parseltongue/core` indexes a single directory into one DocumentIndex. There's no way to index multiple directories and combine them into a unified searchable index. If you want to search across `parseltongue/core` and `parseltongue/llm` together, you have to pick one or re-index everything into a single flat index.

## What we want

An `Index` layer that takes a list of paths, builds per-path DocumentIndexes, and aggregates them into a single queryable index. Each sub-index is independently cached and incrementally updated via Merkle trees. The aggregate index merges results at query time.

## Approach

- `Index(paths: list[str])` — top-level object
- Each path gets its own `DocumentIndex` with its own Merkle cache
- Adding/removing a path doesn't invalidate other sub-indexes
- Query fans out to all sub-indexes, merges posting sets
- Incremental: only the sub-index whose files changed gets re-indexed
- `pg-bench index path1 path2 path3` — index multiple directories in one command
