"""Qt-free façade the HTTP layer calls into.

Every method here is a thin wrapper around an existing analyzer/runtime/
providers call — the exact same functions `ui/controller.py` already calls.
Nothing is reimplemented; this module exists only because `CoachController`
is Qt-shaped (owns a live QThread for async scans, page-registration
plumbing) and is therefore unsafe to call from an HTTP server's worker
threads. See docs/VSCODE_INTEGRATION_ARCHITECTURE.md §5.

Each call constructs its own short-lived `ClaudeCodeEnvironmentProvider`/
`RuntimeCoach` — cheap, stateless besides the database, and safe to call
from any thread since `database/db.py` already opens a fresh sqlite3
connection per call.
"""

from __future__ import annotations

from pathlib import Path

from ..database import db
from ..providers import ClaudeCodeEnvironmentProvider
from ..runtime.event_source import HookFileEventSource
from ..runtime.runtime_coach import RuntimeCoach
from . import models


def _events_dir() -> Path:
    # Mirrors ui/controller.py's own note: derive from DB_PATH.parent (not
    # the module-level APP_DIR constant), so tests overriding db.DB_PATH
    # stay isolated.
    return db.DB_PATH.parent / "runtime_events"


def _default_project_root() -> str | None:
    return db.get_setting("project_root") or None


def _drain_runtime_events() -> int:
    """Pull-based freshness: drain any pending hook events into SQLite right
    before answering a request, so a VS Code query is never stale just
    because nobody happened to have the desktop Sessions page open
    (Phase 1 Finding V5-2). Cheap — reading a handful of small JSONL files.
    """
    coach = RuntimeCoach(source=HookFileEventSource(_events_dir()))
    return coach.poll_and_store()


def health() -> dict:
    return models.health_response()


def status(project_root: str | None = None) -> dict:
    root = project_root or _default_project_root()
    _drain_runtime_events()
    coach = RuntimeCoach(source=HookFileEventSource(_events_dir()))
    runtime_status = coach.status()
    return models.status_response(
        connected=True,
        runtime_configured=runtime_status.hooks_installed,
        runtime_state=runtime_status.state.value,
        project_root=root,
        last_event_at=runtime_status.last_event_at,
    )


def session(cwd: str | None = None, project_root: str | None = None) -> dict:
    resolved_cwd = cwd or project_root or _default_project_root()
    _drain_runtime_events()
    coach = RuntimeCoach(source=HookFileEventSource(_events_dir()))
    runtime_status = coach.status(cwd=resolved_cwd)
    return models.session_response(runtime_status, cwd=resolved_cwd)


def environment(project_root: str | None = None) -> dict:
    root = project_root or _default_project_root()
    provider = ClaudeCodeEnvironmentProvider(project_root=root, user_home=Path.home())
    snapshot = provider.scan()
    return models.environment_response(snapshot)


def new_events_since_last_drain() -> int:
    """Used by the background signal loop — see service/lifecycle.py."""
    return _drain_runtime_events()
