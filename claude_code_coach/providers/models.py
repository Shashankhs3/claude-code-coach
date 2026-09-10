"""Typed models for real Claude Code environment discovery (V3.1).

These are plain data — no Qt, no sqlite — so the UI and the analyzer both
consume the same shapes. Nothing in this module fabricates data: every
field here is either read from an actual file on disk or explicitly marked
unknown/absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Source(str, Enum):
    """Where a discovered item lives."""
    PROJECT = "project"
    PARENT = "parent"       # a CLAUDE.md found while walking up from the project root
    USER = "user"           # global, under the user's home Claude config
    UNKNOWN = "unknown"


class Provenance(str, Enum):
    """The core V3.1 distinction (spec section 22): what kind of claim this is.

    DETECTED  - an actual file/config entry found on disk right now.
    POSSIBLE  - a match between a prompt and a DETECTED resource (confidence-rated).
    INFERRED  - the coach's own historical-pattern heuristic (V3's existing
                Skill/Agent-candidate signal) — no real resource was found.
    UNKNOWN   - discovery could not be completed (e.g. permission denied).
    """
    DETECTED = "detected"
    POSSIBLE = "possible"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


@dataclass
class ClaudeMdInfo:
    path: str
    scope: Source
    size_bytes: int
    modified: str  # ISO 8601
    preview: str = ""  # short, secret-redacted preview — never full contents


@dataclass
class SkillInfo:
    name: str
    path: str
    description: str
    source: Source
    modified: str


@dataclass
class AgentInfo:
    name: str
    path: str
    description: str
    source: Source
    modified: str


@dataclass
class McpServerInfo:
    name: str
    server_type: str          # "stdio" | "sse" | "http" | "unknown"
    source: Source
    config_path: str
    enabled: bool | None = None  # None = not determinable from local config


@dataclass
class EnvironmentSnapshot:
    scanned_at: str
    project_root: str | None
    claude_md: list[ClaudeMdInfo] = field(default_factory=list)
    skills: list[SkillInfo] = field(default_factory=list)
    agents: list[AgentInfo] = field(default_factory=list)
    mcp_servers: list[McpServerInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        return {
            "claude_md": len(self.claude_md),
            "skills": len(self.skills),
            "agents": len(self.agents),
            "mcp_servers": len(self.mcp_servers),
        }

    def is_empty(self) -> bool:
        return not (self.claude_md or self.skills or self.agents or self.mcp_servers)
