# Establish Git-Based Development Tracker

**Branch**: feature/dev-tracker

## Problem

No structured way to track tasks, proposals, and completion across the project. Work happens ad-hoc without a visible queue or historical record.

## What we want

A lightweight, git-native task tracker living in `roadmap/`. Tasks are markdown files that move through `pending/` → `in_progress/` → `completed/` directories. Claiming and completing tasks happens through PRs to master, with `pg-task:<slug>` tags in commits for traceability.

## Proposal

1. Create directory structure: `roadmap/{pending,in_progress,completed}/`
2. Create `TRACKER.md` — single-table overview of all tasks
3. Create `WORKFLOW.md` — explains the lifecycle and conventions
4. Migrate existing task files into the tracker
