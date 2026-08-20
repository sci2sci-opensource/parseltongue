# Roadmap Tracker as a .pgmd Notebook

## Problem

`roadmap/TRACKER.md` is a hand-maintained table with a workflow rule
("keep TRACKER.md in sync with the folder state") that nothing checks.
Task files move between `pending/`, `in_progress/`, and `completed/`,
statuses live redundantly in the table, and drift is invisible until a
human notices.

## What we want

The tracker as a literate `.pgmd` notebook: prose stays prose, but the
status table is backed by facts, and the sync rule becomes a checked
claim rather than a convention — e.g. corpus claims over the roadmap
directory (a task listed "in progress" must exist under `in_progress/`,
a "done" row must have a `completed/` file, no task file without a
row). `pg-bench render` then produces the human view from the same
source that the consistency check verifies.

## Approach

Small: a `roadmap/tracker.pgmd` with one fact per task + `:absent` /
`:forall` claims over `roadmap/**` (the corpus-evidence machinery
already speaks .pgignore-style scoping), rendered to the current table.
Decide whether TRACKER.md stays as the rendered artifact or is
replaced. Should follow the workflow it describes: this task is the
proposal.
