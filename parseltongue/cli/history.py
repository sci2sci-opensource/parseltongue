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

_MIGRATIONS = [
    "ALTER TABLE runs ADD COLUMN system_state TEXT",
]


def _connect() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_TABLE)
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
                result.output.consistency,
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


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent runs (newest first)."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, timestamp, query, model, status FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
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
