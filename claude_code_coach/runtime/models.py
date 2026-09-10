"""Typed models for the V4 runtime layer.

Scope note (spec section 1 / 34 — no fabrication): this app only claims
support for the Claude Code hook events below. That is a deliberately
smaller set than everything a hooks reference document may describe —
these are the events independently cross-checked against this project's
own real, locally-observed Claude Code configuration (`~/.claude/settings.json`
already had Stop/PermissionRequest/PreToolUse/UserPromptSubmit/SubagentStop
configured) plus the well-established core lifecycle events. Anything else
is simply not wired up, not silently pretended to work.

Source: https://code.claude.com/docs/en/hooks (fetched during development)
cross-checked against local `~/.claude/settings.json` and `~/.claude.json`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RuntimeEventType(str, Enum):
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    STOP = "Stop"
    SUBAGENT_STOP = "SubagentStop"
    PRE_COMPACT = "PreCompact"
    NOTIFICATION = "Notification"
    PERMISSION_REQUEST = "PermissionRequest"
    UNKNOWN = "Unknown"

    @classmethod
    def from_hook_name(cls, name: str) -> "RuntimeEventType":
        try:
            return cls(name)
        except ValueError:
            return cls.UNKNOWN


class ConnectionState(str, Enum):
    """Spec section 2's explicit, non-fabricated states."""
    LIVE = "live"                    # an event arrived within the freshness window
    CONNECTED = "connected"          # events exist historically, none recently
    CONFIGURED = "configured"        # hooks installed by this app, no event ever seen yet
    NOT_CONFIGURED = "not_configured"  # hooks never installed by this app
    UNAVAILABLE = "unavailable"      # something about the local runtime store is broken
    UNKNOWN = "unknown"


@dataclass
class RuntimeEvent:
    id: int | None
    received_at: str          # when this app's receiver captured it (ISO)
    session_id: str
    event_type: RuntimeEventType
    tool_name: str | None = None
    metadata: dict = field(default_factory=dict)
    content: str | None = None  # only populated if content-collection is opted in

    def to_row(self) -> dict:
        return {
            "received_at": self.received_at,
            "session_id": self.session_id,
            "event_type": self.event_type.value,
            "tool_name": self.tool_name or "",
            "metadata_json": self.metadata,
            "content": self.content,
        }


@dataclass
class RuntimeSignal:
    kind: str          # e.g. "broad_exploration", "search_first_good", "repeated_instructions"
    level: str          # "low" | "medium" | "high" (spec section 21)
    message: str
    what_happened: str = ""
    why_it_matters: str = ""
    try_instead: str = ""
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "level": self.level, "message": self.message,
            "what_happened": self.what_happened, "why_it_matters": self.why_it_matters,
            "try_instead": self.try_instead, "evidence": self.evidence,
        }


@dataclass
class SessionSummary:
    session_id: str
    started_at: str
    last_event_at: str
    prompts: int = 0
    tool_calls: int = 0
    searches: int = 0
    reads: int = 0
    edits: int = 0
    commands: int = 0
    skills_or_agents: int = 0
    compactions: int = 0
    ended: bool = False


@dataclass
class RuntimeStatus:
    state: ConnectionState
    last_event_at: str | None
    hooks_installed: bool
    hooks_install_path: str | None
    current_session: SessionSummary | None
    signals: list[RuntimeSignal] = field(default_factory=list)
    context_health: int | None = None  # 0-100, local heuristic — see runtime_analyzer.session_coherence
