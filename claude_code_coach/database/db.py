"""SQLite access layer for Claude Code Coach.

All reads/writes go through this module so the rest of the app never touches
sqlite3 directly and never has to worry about legacy/malformed data shapes.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .migrations import ensure_schema

APP_DIR = Path.home() / ".claude_code_coach"
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "coach.db"


def safe_score(value: Any) -> int:
    """Safely coerce any legacy/foreign value into an int score in [0, 100].

    This exists because earlier prototypes could persist scores as strings,
    which crashes plain ``int + str`` arithmetic in Dashboard/Habits
    calculations. Every place that reads a score from the database (or from
    user-editable import data) must go through this function.
    """
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
            return 0
    return max(0, min(100, score))


def _safe_json_list(value: Any) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        ensure_schema(conn)


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["score"] = safe_score(d.get("score"))
    d["breadth_level"] = safe_score(d.get("breadth_level")) if d.get("breadth_level") else 0
    d["good"] = _safe_json_list(d.get("good_json"))
    d["warnings"] = _safe_json_list(d.get("warnings_json"))
    d["opportunities"] = _safe_json_list(d.get("opportunities_json"))
    return d


def insert_prompt(record: dict) -> int:
    """Insert one analyzed prompt. `record` uses AnalysisResult.to_row()."""
    with get_connection() as conn:
        ensure_schema(conn)
        cur = conn.execute(
            """
            INSERT INTO prompts (
                timestamp, prompt, score, rating, task_type,
                goal_status, scope_status, investigation_status,
                constraints_status, done_status, output_status,
                good_json, warnings_json, opportunities_json,
                breadth_level, context_flag
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["timestamp"],
                record["prompt"],
                safe_score(record.get("score")),
                record.get("rating", ""),
                record.get("task_type", ""),
                record.get("goal_status", ""),
                record.get("scope_status", ""),
                record.get("investigation_status", ""),
                record.get("constraints_status", ""),
                record.get("done_status", ""),
                record.get("output_status", ""),
                json.dumps(record.get("good", [])),
                json.dumps(record.get("warnings", [])),
                json.dumps(record.get("opportunities", [])),
                int(record.get("breadth_level", 0) or 0),
                record.get("context_flag", "") or "",
            ),
        )
        conn.commit()
        return cur.lastrowid


def fetch_all_prompts(limit: int | None = None) -> list[dict]:
    with get_connection() as conn:
        ensure_schema(conn)
        sql = "SELECT * FROM prompts ORDER BY id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql).fetchall()
        return [_row_to_dict(r) for r in rows]


def fetch_prompt(row_id: int) -> dict | None:
    with get_connection() as conn:
        ensure_schema(conn)
        row = conn.execute("SELECT * FROM prompts WHERE id = ?", (row_id,)).fetchone()
        return _row_to_dict(row) if row else None


def clear_all() -> None:
    """Delete all prompt history and discovered-environment data.

    ``app_settings`` (e.g. the chosen project root, scan-on-startup
    preference) is configuration, not collected data, and survives a clear
    — same reasoning as not resetting app preferences when clearing browser
    history.
    """
    with get_connection() as conn:
        ensure_schema(conn)
        conn.execute("DELETE FROM prompts")
        conn.execute(
            "UPDATE sqlite_sequence SET seq = 0 WHERE name = 'prompts'"
        ) if _has_sqlite_sequence(conn) else None
        conn.execute("DELETE FROM environment_scans")
        conn.execute("DELETE FROM claude_md_metadata")
        conn.execute("DELETE FROM skills_metadata")
        conn.execute("DELETE FROM agents_metadata")
        conn.execute("DELETE FROM mcp_metadata")
        conn.execute("DELETE FROM runtime_events")
        conn.execute("DELETE FROM runtime_sessions")
        conn.execute("DELETE FROM skill_creator_draft")
        conn.execute("DELETE FROM agent_creator_draft")
        conn.commit()
        conn.execute("VACUUM")


def _has_sqlite_sequence(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
    ).fetchone()
    return row is not None


def count_prompts() -> int:
    with get_connection() as conn:
        ensure_schema(conn)
        row = conn.execute("SELECT COUNT(*) FROM prompts").fetchone()
        return int(row[0]) if row else 0


def db_info() -> dict:
    size_bytes = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    return {
        "path": str(DB_PATH),
        "size_bytes": size_bytes,
        "size_human": _human_size(size_bytes),
        "prompt_count": count_prompts(),
    }


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _enum_value(x: Any) -> Any:
    return x.value if hasattr(x, "value") else x


def save_environment_snapshot(snapshot) -> None:
    """Persist an EnvironmentSnapshot's metadata only — never file contents,
    previews are already secret-redacted by the provider, and MCP server
    args/env are never captured at all (see providers.models.McpServerInfo).
    Always replaces the previous "latest scan" wholesale.
    """
    with get_connection() as conn:
        ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO environment_scans
                (id, scanned_at, project_root, claude_md_count, skills_count,
                 agents_count, mcp_count, errors_json)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                scanned_at = excluded.scanned_at,
                project_root = excluded.project_root,
                claude_md_count = excluded.claude_md_count,
                skills_count = excluded.skills_count,
                agents_count = excluded.agents_count,
                mcp_count = excluded.mcp_count,
                errors_json = excluded.errors_json
            """,
            (
                snapshot.scanned_at, snapshot.project_root,
                len(snapshot.claude_md), len(snapshot.skills),
                len(snapshot.agents), len(snapshot.mcp_servers),
                json.dumps(snapshot.errors),
            ),
        )

        conn.execute("DELETE FROM claude_md_metadata")
        conn.executemany(
            "INSERT INTO claude_md_metadata (path, scope, size_bytes, modified, preview) "
            "VALUES (?, ?, ?, ?, ?)",
            [(d.path, _enum_value(d.scope), d.size_bytes, d.modified, d.preview)
             for d in snapshot.claude_md],
        )

        conn.execute("DELETE FROM skills_metadata")
        conn.executemany(
            "INSERT INTO skills_metadata (name, path, description, source, modified) "
            "VALUES (?, ?, ?, ?, ?)",
            [(s.name, s.path, s.description, _enum_value(s.source), s.modified)
             for s in snapshot.skills],
        )

        conn.execute("DELETE FROM agents_metadata")
        conn.executemany(
            "INSERT INTO agents_metadata (name, path, description, source, modified) "
            "VALUES (?, ?, ?, ?, ?)",
            [(a.name, a.path, a.description, _enum_value(a.source), a.modified)
             for a in snapshot.agents],
        )

        conn.execute("DELETE FROM mcp_metadata")
        conn.executemany(
            "INSERT INTO mcp_metadata (name, server_type, source, config_path, enabled) "
            "VALUES (?, ?, ?, ?, ?)",
            [(m.name, m.server_type, _enum_value(m.source), m.config_path,
              None if m.enabled is None else int(m.enabled))
             for m in snapshot.mcp_servers],
        )
        conn.commit()


def fetch_environment_snapshot() -> dict | None:
    """Return the most recently persisted scan's metadata, or None if never scanned."""
    with get_connection() as conn:
        ensure_schema(conn)
        row = conn.execute("SELECT * FROM environment_scans WHERE id = 1").fetchone()
        if not row:
            return None
        summary = dict(row)
        summary["errors"] = _safe_json_list(summary.get("errors_json"))
        summary["claude_md"] = [dict(r) for r in conn.execute(
            "SELECT * FROM claude_md_metadata ORDER BY id")]
        summary["skills"] = [dict(r) for r in conn.execute(
            "SELECT * FROM skills_metadata ORDER BY id")]
        summary["agents"] = [dict(r) for r in conn.execute(
            "SELECT * FROM agents_metadata ORDER BY id")]
        summary["mcp_servers"] = [dict(r) for r in conn.execute(
            "SELECT * FROM mcp_metadata ORDER BY id")]
        return summary


def get_setting(key: str, default: str | None = None) -> str | None:
    with get_connection() as conn:
        ensure_schema(conn)
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default


def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        conn.commit()


# -- V5: Skill/Agent Creator draft persistence -----------------------------
def _get_draft(table: str) -> dict | None:
    with get_connection() as conn:
        ensure_schema(conn)
        row = conn.execute(f"SELECT draft_json FROM {table} WHERE id = 1").fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except ValueError:
            return None


def _save_draft(table: str, draft: dict) -> None:
    with get_connection() as conn:
        ensure_schema(conn)
        conn.execute(
            f"INSERT INTO {table} (id, draft_json) VALUES (1, ?) "
            f"ON CONFLICT(id) DO UPDATE SET draft_json = excluded.draft_json",
            (json.dumps(draft),),
        )
        conn.commit()


def _clear_draft(table: str) -> None:
    with get_connection() as conn:
        ensure_schema(conn)
        conn.execute(f"DELETE FROM {table}")
        conn.commit()


def get_skill_draft() -> dict | None:
    return _get_draft("skill_creator_draft")


def save_skill_draft(draft: dict) -> None:
    _save_draft("skill_creator_draft", draft)


def clear_skill_draft() -> None:
    _clear_draft("skill_creator_draft")


def get_agent_draft() -> dict | None:
    return _get_draft("agent_creator_draft")


def save_agent_draft(draft: dict) -> None:
    _save_draft("agent_creator_draft", draft)


def clear_agent_draft() -> None:
    _clear_draft("agent_creator_draft")


# -- V4: runtime events --------------------------------------------------------
# Kept as a self-contained taxonomy here (rather than imported from the
# `runtime` package) to avoid the database layer depending on a higher layer.
_SEARCH_TOOLS = {"Grep", "Glob", "WebSearch"}
_READ_TOOLS = {"Read"}
_EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
_EXEC_TOOLS = {"Bash"}


def insert_runtime_event(event) -> int:
    """Insert one RuntimeEvent and update its session's running summary.

    Accepts a `runtime.models.RuntimeEvent`-shaped object (duck-typed, so
    this module doesn't need to import the runtime package).
    """
    with get_connection() as conn:
        ensure_schema(conn)
        row = event.to_row() if hasattr(event, "to_row") else event
        cur = conn.execute(
            "INSERT INTO runtime_events (received_at, session_id, event_type, "
            "tool_name, metadata_json, content) VALUES (?, ?, ?, ?, ?, ?)",
            (
                row["received_at"], row["session_id"], row["event_type"],
                row.get("tool_name", ""), json.dumps(row.get("metadata_json", {})),
                row.get("content"),
            ),
        )
        _apply_session_update(conn, row)
        conn.commit()
        return cur.lastrowid


def _apply_session_update(conn: sqlite3.Connection, row: dict) -> None:
    session_id = row["session_id"]
    received_at = row["received_at"]
    event_type = row["event_type"]
    tool_name = row.get("tool_name") or ""

    existing = conn.execute(
        "SELECT session_id FROM runtime_sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO runtime_sessions (session_id, started_at, last_event_at) "
            "VALUES (?, ?, ?)",
            (session_id, received_at, received_at),
        )

    increments = {"prompts": 0, "tool_calls": 0, "searches": 0, "reads": 0,
                  "edits": 0, "commands": 0, "skills_or_agents": 0, "compactions": 0}

    if event_type == "UserPromptSubmit":
        increments["prompts"] = 1
    elif event_type == "PreToolUse":
        increments["tool_calls"] = 1
        if tool_name in _SEARCH_TOOLS:
            increments["searches"] = 1
        elif tool_name in _READ_TOOLS:
            increments["reads"] = 1
        elif tool_name in _EDIT_TOOLS:
            increments["edits"] = 1
        elif tool_name in _EXEC_TOOLS:
            increments["commands"] = 1
    elif event_type == "SubagentStop":
        increments["skills_or_agents"] = 1
    elif event_type == "PreCompact":
        increments["compactions"] = 1

    set_clause = ", ".join(f"{k} = {k} + ?" for k in increments)
    conn.execute(
        f"UPDATE runtime_sessions SET last_event_at = ?, {set_clause} WHERE session_id = ?",
        [received_at, *increments.values(), session_id],
    )
    if event_type == "SessionEnd":
        conn.execute(
            "UPDATE runtime_sessions SET ended = 1 WHERE session_id = ?", (session_id,)
        )


def fetch_runtime_events(session_id: str | None = None, limit: int | None = None) -> list[dict]:
    with get_connection() as conn:
        ensure_schema(conn)
        sql = "SELECT * FROM runtime_events"
        params: list = []
        if session_id:
            sql += " WHERE session_id = ?"
            params.append(session_id)
        sql += " ORDER BY id ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql, params).fetchall()
        return [_runtime_event_row_to_dict(r) for r in rows]


def _runtime_event_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    try:
        d["metadata"] = json.loads(d.get("metadata_json") or "{}")
    except ValueError:
        d["metadata"] = {}
    return d


def list_runtime_sessions(limit: int | None = None) -> list[dict]:
    with get_connection() as conn:
        ensure_schema(conn)
        sql = "SELECT * FROM runtime_sessions ORDER BY last_event_at DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return [dict(r) for r in conn.execute(sql).fetchall()]


def get_runtime_session(session_id: str) -> dict | None:
    with get_connection() as conn:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT * FROM runtime_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def purge_runtime_events_older_than(days: int) -> int:
    """Delete runtime events (and now-orphaned sessions) older than N days."""
    with get_connection() as conn:
        ensure_schema(conn)
        cutoff = conn.execute(
            "SELECT datetime('now', ?)", (f"-{int(days)} days",)
        ).fetchone()[0]
        cur = conn.execute(
            "DELETE FROM runtime_events WHERE received_at < ?", (cutoff,)
        )
        conn.execute(
            "DELETE FROM runtime_sessions WHERE session_id NOT IN "
            "(SELECT DISTINCT session_id FROM runtime_events)"
        )
        conn.commit()
        return cur.rowcount


def export_json(path: Path) -> int:
    """Export all prompt history to a JSON file. Returns the row count."""
    rows = fetch_all_prompts()
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return len(rows)


def import_json(path: Path) -> int:
    """Import prompt history from a previously exported JSON file.

    Unknown/malformed fields are ignored safely; scores are normalized.
    Returns the number of rows imported.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Import file must contain a JSON list of prompt records.")

    imported = 0
    for item in data:
        if not isinstance(item, dict) or not item.get("prompt"):
            continue
        record = {
            "timestamp": item.get("timestamp", ""),
            "prompt": str(item.get("prompt", "")),
            "score": safe_score(item.get("score")),
            "rating": str(item.get("rating", "")),
            "task_type": str(item.get("task_type", "")),
            "goal_status": str(item.get("goal_status", "")),
            "scope_status": str(item.get("scope_status", "")),
            "investigation_status": str(item.get("investigation_status", "")),
            "constraints_status": str(item.get("constraints_status", "")),
            "done_status": str(item.get("done_status", "")),
            "output_status": str(item.get("output_status", "")),
            "good": _safe_json_list(item.get("good")),
            "warnings": _safe_json_list(item.get("warnings")),
            "opportunities": _safe_json_list(item.get("opportunities")),
            "breadth_level": safe_score(item.get("breadth_level")) if item.get("breadth_level") else 0,
            "context_flag": str(item.get("context_flag", "")),
        }
        insert_prompt(record)
        imported += 1
    return imported
