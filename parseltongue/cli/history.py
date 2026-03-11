"""Run history — SQLite storage for past pipeline runs + cached results."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("parseltongue.cli")

DB_DIR = Path.home() / ".parseltongue" / "cli"
DB_PATH = DB_DIR / "history.db"

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT    NOT NULL,
    query        TEXT    NOT NULL,
    model        TEXT    NOT NULL,
    base_url     TEXT    NOT NULL,
    documents    TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'running',
    error        TEXT,
    pass1_source TEXT,
    pass2_source TEXT,
    pass3_source TEXT,
    pass4_raw    TEXT,
    output_md    TEXT,
    refs         TEXT,
    consistency  TEXT,
    system_state TEXT
)
"""

_CREATE_PROJECTS_TABLE = """
CREATE TABLE IF NOT EXISTS projects (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    project_dir  TEXT    NOT NULL,
    entry_point  TEXT    NOT NULL,
    last_opened  TEXT    NOT NULL,
    open_files   TEXT    NOT NULL DEFAULT '[]'
)
"""

_MIGRATIONS = [
    "ALTER TABLE runs ADD COLUMN system_state TEXT",
    # Drop UNIQUE(project_dir, entry_point) — recreate table without it
    """CREATE TABLE IF NOT EXISTS projects_new (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        name         TEXT    NOT NULL,
        project_dir  TEXT    NOT NULL,
        entry_point  TEXT    NOT NULL,
        last_opened  TEXT    NOT NULL,
        open_files   TEXT    NOT NULL DEFAULT '[]'
    )""",
    "INSERT OR IGNORE INTO projects_new SELECT * FROM projects",
    "DROP TABLE projects",
    "ALTER TABLE projects_new RENAME TO projects",
]


def _connect() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_TABLE)
    conn.execute(_CREATE_PROJECTS_TABLE)
    for migration in _MIGRATIONS:
        try:
            conn.execute(migration)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    return conn


def save_run(
    query: str,
    model: str,
    base_url: str,
    documents: list[dict[str, str]],
) -> int:
    """Insert a new run with status='running'.  Returns the run id."""
    conn = _connect()
    try:
        cur = conn.execute(
            """INSERT INTO runs (timestamp, query, model, base_url, documents, status)
               VALUES (?, ?, ?, ?, ?, 'running')""",
            (
                datetime.now(timezone.utc).isoformat(),
                query,
                model,
                base_url,
                json.dumps(documents),
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def complete_run(run_id: int, result: Any) -> None:
    """Update a run with cached pipeline results and mark completed.

    ``result`` is a ``PipelineResult`` (imported lazily to avoid circular deps).
    """
    refs_json = json.dumps(
        [
            {
                "type": r.type,
                "name": r.name,
                "value": str(r.value) if r.value is not None else None,
                "error": r.error,
            }
            for r in result.output.references
        ]
    )

    system_json = ""
    if hasattr(result, "system") and result.system is not None:
        try:
            system_json = json.dumps(result.system.to_dict())
        except Exception:
            log.warning("Failed to serialize system state", exc_info=True)

    conn = _connect()
    try:
        conn.execute(
            """UPDATE runs
               SET status       = 'completed',
                   pass1_source = ?,
                   pass2_source = ?,
                   pass3_source = ?,
                   pass4_raw    = ?,
                   output_md    = ?,
                   refs         = ?,
                   consistency  = ?,
                   system_state = ?
               WHERE id = ?""",
            (
                result.pass1_source,
                result.pass2_source,
                result.pass3_source,
                result.pass4_raw,
                str(result.output),
                refs_json,
                (
                    json.dumps(result.output.consistency)
                    if isinstance(result.output.consistency, dict)
                    else result.output.consistency
                ),
                system_json,
                run_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def fail_run(run_id: int, error: str) -> None:
    """Mark a run as failed."""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE runs SET status = 'failed', error = ? WHERE id = ?",
            (error, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_runs(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Return recent runs (newest first) with pagination."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, timestamp, query, model, status FROM runs ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_run(run_id: int) -> dict[str, Any] | None:
    """Return full run data including cached results, or None."""
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_run(run_id: int) -> None:
    """Delete a single run."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        conn.commit()
    finally:
        conn.close()


def clear_history() -> int:
    """Delete all runs.  Returns count of deleted rows."""
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM runs")
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Project history
# ---------------------------------------------------------------------------


def save_project(
    project_dir: str,
    entry_point: str,
    open_files: list[str] | None = None,
    *,
    project_id: int | None = None,
) -> int:
    """Insert or update a project.  Returns the project id.

    If *project_id* is given, updates that row.  Otherwise inserts a new row.
    """
    name = Path(project_dir).name
    now = datetime.now(timezone.utc).isoformat()
    files_json = json.dumps(open_files or [])
    conn = _connect()
    try:
        if project_id is not None:
            conn.execute(
                """UPDATE projects
                   SET name = ?, project_dir = ?, entry_point = ?,
                       last_opened = ?, open_files = ?
                   WHERE id = ?""",
                (name, project_dir, entry_point, now, files_json, project_id),
            )
            conn.commit()
            return project_id
        else:
            cur = conn.execute(
                """INSERT INTO projects (name, project_dir, entry_point, last_opened, open_files)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, project_dir, entry_point, now, files_json),
            )
            conn.commit()
            return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


def list_projects(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent projects (most recently opened first)."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY last_opened DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_project(project_id: int) -> dict[str, Any] | None:
    """Return a single project by id, or None."""
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_project(project_id: int) -> None:
    """Delete a project from history."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Run → Project export
# ---------------------------------------------------------------------------


def export_run_as_project(run_id: int, target_dir: Path) -> Path:
    """Export a completed run as a project folder.

    Structure:
        resources/          — document .txt files
        sources/
            pass1.pltg      — cross-pass refs patched (pass1.name)
            pass2.pltg
            pass3.pltg
        main.pgmd           — entry point: imports + markdown with namespaced refs

    Passes are siblings in sources/, so cross-refs use short names
    (pass1.name).  The pgmd imports via (import (quote sources.pass1)),
    so its refs use sources.pass1.name.

    Returns the path to main.pgmd (the entry point).
    """
    run = get_run(run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    target_dir.mkdir(parents=True, exist_ok=True)

    # Write document resources
    documents: dict[str, str] = {}
    if run.get("system_state"):
        try:
            ss = json.loads(run["system_state"])
            documents = ss.get("documents", {})
        except (json.JSONDecodeError, TypeError):
            pass

    if documents:
        res_dir = target_dir / "resources"
        res_dir.mkdir(exist_ok=True)
        for doc_name, doc_text in documents.items():
            (res_dir / f"{doc_name}.txt").write_text(doc_text)

    # Collect pass sources with full module names (sources.pass1, etc.)
    # These match the import names from the pgmd entry point.
    pass_entries: list[tuple[str, str, str, str]] = []  # (full_module, short_name, filename, source)
    for key, filename in [
        ("pass1_source", "pass1.pltg"),
        ("pass2_source", "pass2.pltg"),
        ("pass3_source", "pass3.pltg"),
    ]:
        source = run.get(key)
        if source:
            short = key.replace("_source", "")  # "pass1"
            full = f"sources.{short}"  # "sources.pass1"
            pass_entries.append((full, short, filename, source))

    # Resolve names across passes using SHORT module names (pass1, pass2, ...)
    # because pass files are siblings in sources/ and import each other as (import (quote pass1)).
    # The pgmd imports them as sources.pass1, but that's handled separately.
    from parseltongue.cli.export_resolver import namespace_refs, resolve_export_names  # noqa: E402

    patched_sources, bare_to_ns_short = resolve_export_names([(short, source) for _, short, _, source in pass_entries])

    # Build full bare_to_ns for pgmd refs (sources.pass1.name)
    bare_to_ns = {bare: f"sources.{mod}" for bare, mod in bare_to_ns_short.items()}

    # Write patched pass sources
    sources_dir = target_dir / "sources"
    sources_dir.mkdir(exist_ok=True)
    for _, short, filename, _ in pass_entries:
        (sources_dir / filename).write_text(patched_sources[short])

    # Build main.pgmd
    header_lines = ["```scheme", ";; pltg"]
    for doc_name in documents:
        header_lines.append(f'(load-document "{doc_name}" "resources/{doc_name}.txt")')
    for full, _, _, _ in pass_entries:
        header_lines.append(f"(import (quote {full}))")
    header_lines.append("```")
    header_lines.append("")

    # Namespace refs in the markdown output
    output = run.get("output_md", "")
    if bare_to_ns and output:
        output = namespace_refs(output, bare_to_ns)

    entry = target_dir / "main.pgmd"
    entry.write_text("\n".join(header_lines) + output + "\n")
    return entry
