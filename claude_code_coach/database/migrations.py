"""Schema versioning and migrations for the Coach database.

The V2 prototype stored prompts in a table with no schema_version tracking
and — critically — could persist ``score`` as a string in some legacy code
paths. This module makes upgrades from that prototype (or from any older
version of this app) safe: it never assumes the table has the columns the
current app expects, and it normalizes legacy score values instead of
crashing on ``int + str``.
"""

from __future__ import annotations

import sqlite3

CURRENT_SCHEMA_VERSION = 5

# Columns required by the current (V3) "prompts" table, and the default
# value used to backfill them when migrating an older database.
_V3_COLUMNS: dict[str, str] = {
    "timestamp": "''",
    "prompt": "''",
    "score": "0",
    "rating": "''",
    "task_type": "''",
    "goal_status": "''",
    "scope_status": "''",
    "investigation_status": "''",
    "constraints_status": "''",
    "done_status": "''",
    "output_status": "''",
    "good_json": "'[]'",
    "warnings_json": "'[]'",
    "opportunities_json": "'[]'",
    "breadth_level": "0",
    "context_flag": "''",
}


def _safe_score_py(value) -> int:
    """Normalize a legacy score value (possibly a string, float, or None)."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        score = int(round(value))
    else:
        try:
            score = int(round(float(str(value).strip())))
        except (ValueError, TypeError):
            score = 0
    return max(0, min(100, score))


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _create_fresh_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            prompt TEXT NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            rating TEXT NOT NULL DEFAULT '',
            task_type TEXT NOT NULL DEFAULT '',
            goal_status TEXT NOT NULL DEFAULT '',
            scope_status TEXT NOT NULL DEFAULT '',
            investigation_status TEXT NOT NULL DEFAULT '',
            constraints_status TEXT NOT NULL DEFAULT '',
            done_status TEXT NOT NULL DEFAULT '',
            output_status TEXT NOT NULL DEFAULT '',
            good_json TEXT NOT NULL DEFAULT '[]',
            warnings_json TEXT NOT NULL DEFAULT '[]',
            opportunities_json TEXT NOT NULL DEFAULT '[]',
            breadth_level INTEGER NOT NULL DEFAULT 0,
            context_flag TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_prompts_timestamp ON prompts(timestamp)")


def _migrate_legacy_table(conn: sqlite3.Connection) -> None:
    """Bring an older/legacy 'prompts' table up to the current column set."""
    existing = _existing_columns(conn, "prompts")

    for column, default_sql in _V3_COLUMNS.items():
        if column not in existing:
            conn.execute(
                f"ALTER TABLE prompts ADD COLUMN {column} "
                f"{'INTEGER' if column in ('score', 'breadth_level') else 'TEXT'} "
                f"NOT NULL DEFAULT {default_sql}"
            )

    # Legacy V2 prototype used 'created_at' instead of 'timestamp'.
    if "created_at" in existing and "timestamp" in _existing_columns(conn, "prompts"):
        conn.execute(
            "UPDATE prompts SET timestamp = created_at "
            "WHERE (timestamp IS NULL OR timestamp = '') AND created_at IS NOT NULL"
        )

    # Legacy V2 prototype stored a newline-joined opportunities string.
    if "opportunities" in existing:
        rows = conn.execute(
            "SELECT id, opportunities FROM prompts "
            "WHERE opportunities IS NOT NULL AND opportunities != '' "
            "AND (opportunities_json IS NULL OR opportunities_json = '[]')"
        ).fetchall()
        import json

        for row_id, legacy_text in rows:
            lines = [line.strip() for line in str(legacy_text).splitlines() if line.strip()]
            legacy_opps = [
                {"kind": "legacy", "message": line, "confidence": "low"} for line in lines
            ]
            conn.execute(
                "UPDATE prompts SET opportunities_json = ? WHERE id = ?",
                (json.dumps(legacy_opps), row_id),
            )

    # Normalize score to a real integer in [0, 100], even if it was ever
    # stored as a string (the exact bug this migration exists to fix).
    conn.create_function("SAFE_SCORE", 1, _safe_score_py)
    conn.execute("UPDATE prompts SET score = SAFE_SCORE(score)")


# -- V3.1: environment discovery tables -------------------------------------
# These hold only metadata about what was found (name/path/description/
# timestamps) — never file contents, secrets, or MCP server args/env values
# (spec section 17). "environment_scans" is a single-row summary of the most
# recent scan (like schema_version); the four *_metadata tables always hold
# only the latest scan's results and are replaced wholesale on each scan.
def _ensure_v3_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS environment_scans (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            scanned_at TEXT NOT NULL,
            project_root TEXT,
            claude_md_count INTEGER NOT NULL DEFAULT 0,
            skills_count INTEGER NOT NULL DEFAULT 0,
            agents_count INTEGER NOT NULL DEFAULT 0,
            mcp_count INTEGER NOT NULL DEFAULT 0,
            errors_json TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS claude_md_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            scope TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            modified TEXT NOT NULL DEFAULT '',
            preview TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS skills_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL,
            modified TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agents_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL,
            modified TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mcp_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            server_type TEXT NOT NULL DEFAULT 'unknown',
            source TEXT NOT NULL,
            config_path TEXT NOT NULL DEFAULT '',
            enabled INTEGER
        )
        """
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


# -- V4: runtime event tables ------------------------------------------------
# Events are the source of truth; per-session summaries are maintained
# incrementally as events arrive (cheap to keep in sync, avoids re-scanning
# all events on every UI refresh). Coaching *signals* are always recomputed
# on demand from events (same pattern as V3's Skill/Agent candidates) —
# never persisted, so there's nothing to go stale.
def _ensure_v4_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TEXT NOT NULL,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            tool_name TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            content TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_events_session ON runtime_events(session_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_events_received_at ON runtime_events(received_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_sessions (
            session_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            last_event_at TEXT NOT NULL,
            prompts INTEGER NOT NULL DEFAULT 0,
            tool_calls INTEGER NOT NULL DEFAULT 0,
            searches INTEGER NOT NULL DEFAULT 0,
            reads INTEGER NOT NULL DEFAULT 0,
            edits INTEGER NOT NULL DEFAULT 0,
            commands INTEGER NOT NULL DEFAULT 0,
            skills_or_agents INTEGER NOT NULL DEFAULT 0,
            compactions INTEGER NOT NULL DEFAULT 0,
            ended INTEGER NOT NULL DEFAULT 0
        )
        """
    )


# -- V5: in-progress Skill/Agent Creator drafts ------------------------------
# Single-row tables (same pattern as environment_scans) so navigating away
# from the Creator pages doesn't lose unsaved form data. Cleared on explicit
# Save and on "Clear All Local Data".
def _ensure_v5_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS skill_creator_draft "
        "(id INTEGER PRIMARY KEY CHECK (id = 1), draft_json TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS agent_creator_draft "
        "(id INTEGER PRIMARY KEY CHECK (id = 1), draft_json TEXT NOT NULL)"
    )


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create or migrate the database to CURRENT_SCHEMA_VERSION."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (id INTEGER PRIMARY KEY CHECK (id = 1), "
        "version INTEGER NOT NULL)"
    )
    _ensure_v3_tables(conn)
    _ensure_v4_tables(conn)
    _ensure_v5_tables(conn)

    row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    version = row[0] if row else 0

    if version >= CURRENT_SCHEMA_VERSION and _table_exists(conn, "prompts"):
        # Already current, but guard against a half-migrated table anyway.
        missing = set(_V3_COLUMNS) - _existing_columns(conn, "prompts")
        if missing:
            _migrate_legacy_table(conn)
        conn.commit()
        return

    if not _table_exists(conn, "prompts"):
        _create_fresh_schema(conn)
    else:
        _migrate_legacy_table(conn)

    conn.execute(
        "INSERT INTO schema_version (id, version) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET version = excluded.version",
        (CURRENT_SCHEMA_VERSION,),
    )
    conn.commit()
