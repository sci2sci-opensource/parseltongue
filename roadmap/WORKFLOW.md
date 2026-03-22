# Roadmap Workflow

## Directory structure

```
roadmap/
  TRACKER.md              # status overview — single table of all tasks
  WORKFLOW.md             # this file
  pending/                # tasks not yet claimed
  in_progress/            # tasks actively being worked on
  completed/              # finished tasks (merged PRs)
```

Each task is a single `.md` file named with a slug (e.g. `multi-index-search.md`).

## Task lifecycle

```
pending/ ──claim PR──> in_progress/ ──feature PR──> completed/
```

### 1. Propose a task

Create `roadmap/pending/<slug>.md` with at minimum:
- **Problem** — what's wrong or missing
- **What we want** — desired outcome
- **Approach** (optional) — implementation sketch
- **Files likely involved** (optional)

Open a PR to `master` adding the file.

### 2. Claim a task

Open a PR to `master` that:

1. Moves the file from `pending/` to `in_progress/`
2. Adds a **Proposal** section with the planned approach
3. Adds a **Branch** field with the feature branch name
4. Updates `TRACKER.md` — status to `in progress`, branch column filled

This PR is the claim. Review the proposal, merge, then start coding on the feature branch.

### 3. Do the work

Work happens on the feature branch.

### 4. Complete a task

The feature PR itself completes the task. The PR to `master` must include:

1. The implementation changes
2. The task file moved from `in_progress/` to `completed/` with a **Result** section added
3. `TRACKER.md` updated — status to `done`, PR column filled

The merge commit (or a commit in the PR) must contain the tag:

```
pg-task:slug-name
```

For example:

```
Lens diff traversal — diffs visible in probe graph

pg-task:lens-diff-traversal
```

This tag links the merged code to the roadmap task for traceability.

## Task file template

```markdown
# Task Title

**Branch**: feature/my-branch
**PR**: #123

## Problem

What's broken or missing.

## What we want

Desired end state.

## Proposal

How we plan to do it (added when claiming).

## Result

What was actually done (added when completing).
```

## Rules

- One task per file, one file per task
- Claim before coding — the proposal PR is the starting signal, and the fact of task being taken will be visible in master
- The feature PR moves the task to `completed/` and tags the commit with `pg-task:<slug>`
- Keep TRACKER.md in sync with the folder state
- Don't delete completed tasks — they're the historical record
