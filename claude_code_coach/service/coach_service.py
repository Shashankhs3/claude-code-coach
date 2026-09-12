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

from ..analyzer import analyze_prompt
from ..analyzer.prompt_rewriter import suggest_prompt
from ..database import db
from ..integration import recommend_approach
from ..providers import ClaudeCodeEnvironmentProvider
from ..runtime.event_source import HookFileEventSource
from ..runtime.runtime_coach import RuntimeCoach
from . import models

# Phase 3 request-body bound: generous enough for any real prompt, small
# enough to reject an accidental/malicious oversized body before it ever
# reaches the analyzer. Enforced by the HTTP layer (server.py); mirrored
# here as a defense-in-depth check on the value actually passed in.
MAX_PROMPT_LENGTH = 20_000


class InvalidRequestError(ValueError):
    """Raised for a structurally invalid request body — the HTTP layer
    turns this into a 400, never a 500/stack trace."""


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


def _validate_prompt(payload: dict) -> str:
    if not isinstance(payload, dict):
        raise InvalidRequestError("request body must be a JSON object")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise InvalidRequestError("'prompt' must be a non-empty string")
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise InvalidRequestError(f"'prompt' exceeds {MAX_PROMPT_LENGTH} characters")
    return prompt


def analyze(payload: dict) -> dict:
    """Phase 3: POST /api/v1/analyze. Identical call to what
    ui/inspector.py already makes (controller.analyze -> analyzer.
    analyze_prompt) — no analysis logic lives here."""
    prompt = _validate_prompt(payload)
    return models.analysis_response(analyze_prompt(prompt))


def suggest(payload: dict) -> dict:
    """Phase 3: POST /api/v1/suggest. Same call as ui/inspector.py's
    controller.suggest_prompt(text, analysis) — analysis is recomputed
    here rather than accepted from the caller, since this is a stateless
    per-request façade (Phase 2's own design choice, unchanged)."""
    prompt = _validate_prompt(payload)
    analysis = analyze_prompt(prompt)
    return models.suggestion_response(suggest_prompt(prompt, analysis))


def approach(payload: dict) -> dict:
    """Phase 3: POST /api/v1/approach. Same call as ui/controller.py's
    recommend_approach(text, analysis) -> integration.recommend_approach,
    with the same real environment_snapshot and runtime_status a desktop
    Approach Advisor call would use. project_root in the body scopes the
    environment scan; cwd scopes the runtime session — both optional,
    falling back to the desktop app's own configured project_root."""
    prompt = _validate_prompt(payload)
    project_root = payload.get("project_root")
    if project_root is not None and not isinstance(project_root, str):
        raise InvalidRequestError("'project_root' must be a string when present")
    cwd = payload.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise InvalidRequestError("'cwd' must be a string when present")

    root = project_root or _default_project_root()
    analysis = analyze_prompt(prompt)

    provider = ClaudeCodeEnvironmentProvider(project_root=root, user_home=Path.home())
    snapshot = provider.scan()

    _drain_runtime_events()
    runtime_coach = RuntimeCoach(source=HookFileEventSource(_events_dir()))
    runtime_status = runtime_coach.status(cwd=cwd or root)

    report = recommend_approach(prompt, analysis, snapshot, runtime_status)
    return models.approach_response(report)


def new_events_since_last_drain() -> int:
    """Used by the background signal loop — see service/lifecycle.py."""
    return _drain_runtime_events()


def set_paused(payload: dict) -> dict:
    """Phase 4E: POST /api/v1/pause — the one shared, mutable piece of
    coaching state VS Code needs to change remotely (it has no direct
    coach.db access, unlike Desktop). Writes the same `coaching_paused`
    setting Desktop's own Settings checkbox writes directly (see
    docs/SHARED_COACH_STATE.md §5) and nudges the existing signal file so a
    watching VS Code window refreshes promptly instead of waiting for its
    next poll tick — reuses the mechanism Step 11 requires, never a second
    one. Never touches runtime_enabled/hook event collection/the service
    itself, per the ABSOLUTE RULE that pause only suppresses
    interventions."""
    if not isinstance(payload, dict) or not isinstance(payload.get("paused"), bool):
        raise InvalidRequestError("'paused' must be a boolean")
    paused = payload["paused"]

    from ..runtime.runtime_coach import set_coaching_paused
    set_coaching_paused(paused)

    from . import lifecycle as _lifecycle
    try:
        _lifecycle.notify_state_changed("pause_changed")
    except Exception:  # noqa: BLE001 - the write above already succeeded; a
        # failed signal-file nudge must not turn a real state change into
        # an error response (the next poll tick still picks it up).
        pass

    return {"coaching_paused": paused}
