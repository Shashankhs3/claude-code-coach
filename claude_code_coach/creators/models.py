"""Typed drafts for the Skill/Agent creators (spec Features 3/4)."""

from __future__ import annotations

from dataclasses import dataclass, field

NAME_PATTERN = r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"


@dataclass
class SkillDraft:
    name: str
    purpose: str
    when_to_use: str
    workflow: str
    rules: str = ""
    constraints: str = ""
    avoid: str = ""
    expected_output: str = ""
    examples: str = ""


@dataclass
class AgentDraft:
    name: str
    purpose: str
    role: str
    responsibilities: str
    investigation_instructions: str = ""
    allowed_actions: str = ""
    restrictions: str = ""
    may_modify_source: bool = False
    expected_output: str = ""
    verification_requirements: str = ""


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    already_exists: bool = False
