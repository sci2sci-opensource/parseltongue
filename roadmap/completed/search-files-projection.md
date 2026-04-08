# Search files projection — unique-document operator over posting sets

**Branch**: `feature/decouple-pgignore-from-gitignore`

## Problem

`pg search` and `pg eval '(scope search ...)'` return line-level results — every operator in the search system produces or consumes a posting set keyed by `(document, line)`. When a user wants to know **where** matches live, not the line-level detail, there is no operator to ask. The closest is `(rank "document" query)` which groups *display lines* by document but still emits one entry per matched line.

This forces ad-hoc workarounds: parse the line-level output and dedupe by document on the user's side, or run multiple narrowing queries to reverse-engineer the document set. Neither composes with `(count ...)`, `(limit N ...)`, or any of the other sentence-leaf projections.

The general use case is "discover which files in the corpus contain this concept" — the first move of any cross-codebase exploration. The search engine has the answer (it knows every key's first element), it just has no way to expose it as a value the rest of the language can compose with.

## What we want

A new operator `(files <query>)` that:

1. Takes any posting set (or sr list) as input.
2. Projects it to a list of **unique document names**, preserving the input's iteration order.
3. Composes naturally with the existing operators — `(count (files ...))` for unique-doc count, `(limit N (files ...))` for the top N, `(files (rank "document" ...))` to control ordering by match count, `(files (in "engine.py" ...))` to combine with other filters.
4. Does **not** sort internally. The user controls ordering by composing with `rank` — keeping `files` a pure projection avoids reintroducing the "implicit ordering you have to fight" problem the rest of the search system carefully avoids.

## Proposal

- Add `_files` to the operator dict in `parseltongue/core/inspect/systems/search_system_2.py`.
- Implementation: walk the input's iteration order, build an ordered set of unique document names, return as a list of strings (a sentence-leaf type the rest of the system already handles via `_count`, `_limit`, etc.).
- Handle both posting-set inputs (`dict` keyed by `(doc, line)`) and sr-list inputs (`list` of `(sr doc line col context callers)` forms).
- Symbols, devices, fifos, broken keys: silently skip rather than failing — same defensive posture as other operators in the file.

## Result

`_files` operator added to the search system. Pure projection, no built-in sort, composes with `rank` for any ordering the user wants.

**`parseltongue/core/inspect/systems/search_system_2.py`:**
- New `_files(query)` function, parallel to the existing `_results` and `_limit` projections. Walks the input via `_resolve`, recognizes both `dict` posting sets (extracts `key[0]` as the document name) and `list` sr forms (extracts `entry[1]`), builds an ordered set via a `dict` keyed by document name, returns the list of keys.
- Registered as `Symbol("files")` in the operator dict alongside `count`, `results`, `limit`.
- Order preservation is explicit: the function uses an insertion-ordered dict, no `sorted()`, no implicit dedup-and-reorder. If the user wants alphabetical or by-match-count order, they wrap the input in `(rank ...)` first.

**Sample queries this enables:**

```scheme
;; Just the unique docs containing the term, in raw posting iteration order
(scope search (files (or "openai" "anthropic")))

;; Same but ordered by match count via rank — the canonical "where does
;; this concept live, most-matched first" query
(scope search (files (rank "document" (or "openai" "anthropic"))))

;; Unique-doc count
(scope search (count (files (re "class \\w+Model"))))

;; Top 10 docs with the most matches
(scope search (limit 10 (files (rank "document" (or "tokenA" "tokenB")))))
```

The shape composes through `count`, `limit`, and any future sentence-leaf projection without special-casing.

**Verification:** End-to-end against a real multi-repo workspace, the operator returned 80+ unique documents from a broad union query in a single call, ordered by `(rank "document" ...)`. Previously this required parsing line-level output and deduping by document on the caller side.

**Deferred:** No CLI surface change — `pg search '(files ...)'` already works because `pg search` parses any s-expression query through the existing search system. A dedicated `pg search --files-only` CLI flag could be added later as sugar but adds nothing the operator doesn't already give you.

## Notes

The decision to make `files` a pure projection (no internal sort) was deliberate. An earlier draft sorted alphabetically inside `_files`, which would have hidden the rank-driven ordering and forced users to either accept arbitrary order or build a parallel sort path. Splitting the concerns — `files` does projection, `rank` does ordering — keeps the operator orthogonal and avoids breaking existing rank integrations.
