"""Persistence for runtime events/sessions.

Thin wrapper over `database.db` (which owns the actual SQL) so the runtime
package has its own cohesive API, without duplicating schema/SQL logic that
already lives alongside the rest of this app's persistence code.
"""

from __future__ import annotations

from claude_code_coach.database import db

insert_event = db.insert_runtime_event
fetch_events = db.fetch_runtime_events
list_sessions = db.list_runtime_sessions
get_session = db.get_runtime_session
purge_older_than = db.purge_runtime_events_older_than

__all__ = ["insert_event", "fetch_events", "list_sessions", "get_session", "purge_older_than"]
