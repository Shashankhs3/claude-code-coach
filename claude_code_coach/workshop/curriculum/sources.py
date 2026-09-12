"""Shared source citations, reused across lesson files so the same claim
is never re-verified (or mis-cited) twice. ``verified_on`` records when
this session's own /workshop build checked the claim against the given
source — a future content-refresh pass should re-check and bump it (see
docs on the "Search / update" mechanism in the final report)."""

from __future__ import annotations

from ..models import SourceRef, SourceType

_VERIFIED = "2026-09-12"

ANTHROPIC_CONTEXT_ENGINEERING = SourceRef(
    SourceType.OFFICIAL_ANTHROPIC,
    "Effective context engineering for AI agents",
    url="https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents",
    verified_on=_VERIFIED,
)

ANTHROPIC_LONG_RUNNING_AGENTS = SourceRef(
    SourceType.OFFICIAL_ANTHROPIC,
    "Effective harnesses for long-running agents",
    url="https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents",
    verified_on=_VERIFIED,
)

CLAUDE_CODE_BEST_PRACTICES = SourceRef(
    SourceType.CLAUDE_CODE_DOCUMENTED,
    "Best practices for Claude Code",
    url="https://code.claude.com/docs/en/best-practices",
    verified_on=_VERIFIED,
)

CLAUDE_CODE_SUBAGENTS = SourceRef(
    SourceType.CLAUDE_CODE_DOCUMENTED,
    "Subagents",
    url="https://code.claude.com/docs/en/sub-agents",
    verified_on=_VERIFIED,
)

CLAUDE_CODE_PERMISSIONS = SourceRef(
    SourceType.CLAUDE_CODE_DOCUMENTED,
    "Choose a permission mode",
    url="https://code.claude.com/docs/en/permission-modes",
    verified_on=_VERIFIED,
)

CLAUDE_CODE_MEMORY = SourceRef(
    SourceType.CLAUDE_CODE_DOCUMENTED,
    "CLAUDE.md files",
    url="https://code.claude.com/docs/en/memory",
    verified_on=_VERIFIED,
)

CLAUDE_CODE_SKILLS = SourceRef(
    SourceType.CLAUDE_CODE_DOCUMENTED,
    "Skills",
    url="https://code.claude.com/docs/en/skills",
    verified_on=_VERIFIED,
)

CLAUDE_CODE_HOOKS = SourceRef(
    SourceType.CLAUDE_CODE_DOCUMENTED,
    "Hooks",
    url="https://code.claude.com/docs/en/hooks-guide",
    verified_on=_VERIFIED,
)

CLAUDE_CODE_MCP = SourceRef(
    SourceType.CLAUDE_CODE_DOCUMENTED,
    "MCP",
    url="https://code.claude.com/docs/en/mcp",
    verified_on=_VERIFIED,
)

COMMUNITY_SESSION_HYGIENE = SourceRef(
    SourceType.COMMUNITY_PRACTICE,
    "Widely shared workflow habits",
    note="Common practice among Claude Code users — not an Anthropic requirement.",
)


def coach(note: str = "") -> SourceRef:
    """A Claude Code Coach heuristic — never presented as Anthropic guidance."""
    return SourceRef(SourceType.COACH_HEURISTIC, "Claude Code Coach", note=note)
