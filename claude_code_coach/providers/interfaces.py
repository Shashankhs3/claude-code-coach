"""Interfaces for Claude Code environment/session integration.

V3.1 implements ``EnvironmentProvider`` for real (see
``claude_code_provider.ClaudeCodeEnvironmentProvider``): read-only local
filesystem discovery of CLAUDE.md/Skills/Agents/MCP config.

``SessionProvider``, ``HookProvider`` and ``ContextTelemetryProvider`` are
still forward-looking stubs only (spec section 23) — no real Claude Code
session/hook telemetry exists to read yet, and this version must not
fabricate any. Only the ``Null*`` implementations exist for those.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import EnvironmentSnapshot


class EnvironmentProvider(ABC):
    """Describes what Claude Code capabilities are available in the current project."""

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider can actually perform real discovery."""

    @abstractmethod
    def scan(self) -> EnvironmentSnapshot:
        """Perform a read-only scan and return everything actually found.

        Must never raise for ordinary failure modes (missing directories,
        permission errors, malformed files) — those go into
        ``EnvironmentSnapshot.errors`` instead.
        """


class NullEnvironmentProvider(EnvironmentProvider):
    """Reports nothing, fabricates nothing. Used when discovery is disabled."""

    def is_available(self) -> bool:
        return False

    def scan(self) -> EnvironmentSnapshot:
        from datetime import datetime
        return EnvironmentSnapshot(scanned_at=datetime.now().isoformat(timespec="seconds"),
                                    project_root=None)


class SessionProvider(ABC):
    """Describes the current Claude Code session (context size, history, tool use)."""

    @abstractmethod
    def is_available(self) -> bool:
        """Whether real session telemetry can be read at all."""

    @abstractmethod
    def context_size_hint(self) -> int | None:
        """An approximate context size signal, if the CLI ever exposes one."""

    @abstractmethod
    def message_count(self) -> int | None:
        """Number of turns in the current session, if known."""


class NullSessionProvider(SessionProvider):
    """No live session data exists in this version.

    The Context page falls back to locally recorded prompt-history
    statistics instead, and labels them clearly as local habit signals
    rather than actual session/token measurements.
    """

    def is_available(self) -> bool:
        return False

    def context_size_hint(self) -> int | None:
        return None

    def message_count(self) -> int | None:
        return None


class HookProvider(ABC):
    """Future: read which Claude Code hooks are actually configured.

    Not implemented in V3.1 — reserved so a future version can report real
    hook configuration without changing callers.
    """

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def configured_hooks(self) -> list[str]:
        ...


class NullHookProvider(HookProvider):
    def is_available(self) -> bool:
        return False

    def configured_hooks(self) -> list[str]:
        return []


class ContextTelemetryProvider(ABC):
    """Future: read actual context-window/token usage from a live session.

    Not implemented in V3.1. The Context page continues to use locally
    recorded prompt-habit statistics until a real, safe telemetry source
    exists.
    """

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def current_context_tokens(self) -> int | None:
        ...


class NullContextTelemetryProvider(ContextTelemetryProvider):
    def is_available(self) -> bool:
        return False

    def current_context_tokens(self) -> int | None:
        return None
