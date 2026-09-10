"""Where runtime events actually come from.

The real source (HookFileEventSource) drains the append-only JSONL files
that hook_receiver.py writes — one file per Claude Code session_id, under
APP_DIR/runtime_events/. It never reads anything else, never connects to a
live process, and never invents an event: an empty directory means zero
events, not a fabricated one.

Each poll() atomically renames a session's file aside before reading it (so
a concurrent hook_receiver append lands in a freshly recreated file, never
lost) and deletes the renamed copy once consumed. This means there is no
in-memory "read offset" to lose across app restarts — every observed event
is durably handed to the caller (which persists it to SQLite) exactly once,
by construction, rather than by tracking a byte position that a restart
would otherwise reset to zero and cause every historical line to be
re-ingested as a duplicate.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from .models import RuntimeEvent, RuntimeEventType


class RuntimeEventSource(ABC):
    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def poll(self) -> list[RuntimeEvent]:
        """Return events observed since the last call to poll()."""


class NullRuntimeEventSource(RuntimeEventSource):
    def is_available(self) -> bool:
        return False

    def poll(self) -> list[RuntimeEvent]:
        return []


def _event_from_stored_line(data: dict) -> RuntimeEvent | None:
    try:
        return RuntimeEvent(
            id=None,
            received_at=data["received_at"],
            session_id=data["session_id"],
            event_type=RuntimeEventType.from_hook_name(data["event_type"]),
            tool_name=data.get("tool_name") or None,
            metadata=data.get("metadata") or {},
            content=data.get("content"),
        )
    except (KeyError, TypeError):
        return None


class HookFileEventSource(RuntimeEventSource):
    def __init__(self, events_dir: Path):
        self.events_dir = Path(events_dir)

    def is_available(self) -> bool:
        return True

    def poll(self) -> list[RuntimeEvent]:
        if not self.events_dir.is_dir():
            return []

        new_events: list[RuntimeEvent] = []
        try:
            files = sorted(self.events_dir.glob("*.jsonl"))
        except OSError:
            return []

        for path in files:
            consuming_path = path.with_name(path.name + ".consuming")
            try:
                path.rename(consuming_path)
            except OSError:
                # Being written to right now, already consumed, or a
                # transient race — just try again on the next poll.
                continue

            try:
                with open(consuming_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError:
                lines = []
            finally:
                try:
                    consuming_path.unlink()
                except OSError:
                    pass

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                event = _event_from_stored_line(data)
                if event:
                    new_events.append(event)

        new_events.sort(key=lambda e: e.received_at)
        return new_events
