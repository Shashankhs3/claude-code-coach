"""Top-level runtime orchestrator: source -> store -> analyzer -> RuntimeStatus.

This is what the UI controller talks to. It never fabricates a status —
see `_connection_state()` for exactly how each state (spec section 2) is
derived from real, observable facts (a hooks-installed flag this app itself
set, and real timestamps of events actually received).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from claude_code_coach.database import db

from . import event_store, hook_installer, runtime_analyzer
from .event_source import HookFileEventSource, NullRuntimeEventSource, RuntimeEventSource
from .models import ConnectionState, RuntimeEvent, RuntimeEventType, RuntimeStatus, SessionSummary

FRESHNESS_WINDOW = timedelta(minutes=15)
RECENT_PROMPT_LIMIT = 500


def _events_dir() -> Path:
    # DB_PATH.parent, not the module-level APP_DIR constant — see the same
    # note in ui/controller.py's _build_runtime_source().
    return db.DB_PATH.parent / "runtime_events"


class RuntimeCoach:
    def __init__(self, source: RuntimeEventSource | None = None):
        self.source = source or HookFileEventSource(_events_dir())

    # -- ingestion -------------------------------------------------------------
    def poll_and_store(self) -> int:
        """Drain any new events into the database. Returns how many were stored."""
        if not self.source.is_available():
            return 0
        events = self.source.poll()
        for event in events:
            db.insert_runtime_event(event)
        return len(events)

    # -- hook install/uninstall --------------------------------------------------
    def install(self, settings_path: str) -> dict:
        result = hook_installer.install_hooks(Path(settings_path))
        db.set_setting("runtime_hooks_installed", "1")
        db.set_setting("runtime_hooks_path", result["path"])
        return result

    def uninstall(self, settings_path: str) -> dict:
        result = hook_installer.uninstall_hooks(Path(settings_path))
        db.set_setting("runtime_hooks_installed", "0")
        return result

    def hooks_installed(self) -> bool:
        return db.get_setting("runtime_hooks_installed", "0") == "1"

    def hooks_install_path(self) -> str | None:
        return db.get_setting("runtime_hooks_path")

    # -- status / coaching -------------------------------------------------------
    def status(self, environment_snapshot=None) -> RuntimeStatus:
        sessions = db.list_runtime_sessions(limit=1)
        current = sessions[0] if sessions else None
        last_event_at = current["last_event_at"] if current else None

        state = self._connection_state(last_event_at)

        session_summary = None
        signals: list = []
        context_health = None
        if current:
            session_summary = SessionSummary(
                session_id=current["session_id"], started_at=current["started_at"],
                last_event_at=current["last_event_at"], prompts=current["prompts"],
                tool_calls=current["tool_calls"], searches=current["searches"],
                reads=current["reads"], edits=current["edits"], commands=current["commands"],
                skills_or_agents=current["skills_or_agents"], compactions=current["compactions"],
                ended=bool(current["ended"]),
            )

            session_events = [
                _event_from_db_row(r) for r in db.fetch_runtime_events(current["session_id"])
            ]
            latest_prompt_context = None
            for e in reversed(session_events):
                if e.event_type == RuntimeEventType.USER_PROMPT_SUBMIT:
                    latest_prompt_context = e.metadata
                    break

            claude_mds = environment_snapshot.claude_md if environment_snapshot else None
            signals.extend(runtime_analyzer.analyze_session(
                session_events, current, latest_prompt_context=latest_prompt_context,
                claude_mds=claude_mds,
            ))
            context_health, _coherence_signals = runtime_analyzer.session_coherence(session_events)

            detected_skills = environment_snapshot.skills if environment_snapshot else None
            recent_prompts = [
                _event_from_db_row(r) for r in db.fetch_runtime_events(limit=RECENT_PROMPT_LIMIT)
                if r["event_type"] == "UserPromptSubmit"
            ]
            signals.extend(runtime_analyzer.repeated_instructions_signal(
                recent_prompts, detected_skills=detected_skills,
            ))

        return RuntimeStatus(
            state=state,
            last_event_at=last_event_at,
            hooks_installed=self.hooks_installed(),
            hooks_install_path=self.hooks_install_path(),
            current_session=session_summary,
            signals=signals,
            context_health=context_health,
        )

    def _connection_state(self, last_event_at: str | None) -> ConnectionState:
        if not self.source.is_available():
            return ConnectionState.UNAVAILABLE
        if last_event_at:
            try:
                last = datetime.fromisoformat(last_event_at)
                if datetime.now() - last <= FRESHNESS_WINDOW:
                    return ConnectionState.LIVE
                return ConnectionState.CONNECTED
            except ValueError:
                return ConnectionState.CONNECTED
        if self.hooks_installed():
            return ConnectionState.CONFIGURED
        return ConnectionState.NOT_CONFIGURED

    # -- retention / maintenance -----------------------------------------------
    def purge_older_than(self, days: int) -> int:
        return db.purge_runtime_events_older_than(days)


def _event_from_db_row(row: dict) -> RuntimeEvent:
    return RuntimeEvent(
        id=row.get("id"),
        received_at=row["received_at"],
        session_id=row["session_id"],
        event_type=RuntimeEventType.from_hook_name(row["event_type"]),
        tool_name=row.get("tool_name") or None,
        metadata=row.get("metadata") or {},
        content=row.get("content"),
    )
