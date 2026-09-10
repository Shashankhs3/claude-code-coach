"""Prompt <-> real-environment correlation (V3.1, spec sections 8-11, 22).

This is deliberately a separate, additive module: ``analyze_prompt()`` in
``prompt_analyzer.py`` stays environment-agnostic and unmodified — a prompt
still gets the same quality score with or without a scanned environment.
This module answers a different question: *given what's actually on disk*,
does an existing Skill/Agent/CLAUDE.md rule look relevant to this prompt?

Three states, never collapsed into one (spec sections 10/11):
    "existing"  - a real, DETECTED resource looks relevant (POSSIBLE match)
    "candidate" - no real resource matched, but the prompt/history itself
                  suggests one would help (the existing INFERRED V3 signal)
    "none"      - neither

Confidence is conservative by construction: a match needs a real, sizeable
term overlap between the prompt and the resource's own name/description to
count, and "high" confidence requires a much stronger overlap than
"medium" (spec section 8: "prefer 'possible match' for medium confidence").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..analytics.patterns import tokenize
from ..analyzer.models import AnalysisResult
from ..providers.models import AgentInfo, ClaudeMdInfo, SkillInfo

HIGH_OVERLAP = 0.35
MEDIUM_OVERLAP = 0.15

# CLAUDE.md duplication must not fire on ordinary short clarifications
# (spec section 9: "do not aggressively flag normal clarification").
CLAUDE_MD_MIN_PROMPT_WORDS = 6
CLAUDE_MD_OVERLAP_THRESHOLD = 0.5


@dataclass
class ResourceMatch:
    name: str
    path: str
    confidence: str  # "high" | "medium"
    matched_terms: list[str] = field(default_factory=list)


@dataclass
class EnvironmentFeedback:
    skill_state: str  # "existing" | "candidate" | "none"
    skill_match: ResourceMatch | None = None
    skill_candidate_message: str = ""

    agent_state: str = "none"
    agent_match: ResourceMatch | None = None
    agent_candidate_message: str = ""

    claude_md_duplicate: ResourceMatch | None = None


def _overlap(prompt_tokens: set, resource_text: str) -> tuple[float, list[str]]:
    resource_tokens = tokenize(resource_text)
    if not prompt_tokens or not resource_tokens:
        return 0.0, []
    shared = prompt_tokens & resource_tokens
    score = len(shared) / max(1, len(resource_tokens))
    return score, sorted(shared)


def _best_match(prompt_tokens: set, name: str, path: str, text: str) -> ResourceMatch | None:
    score, shared = _overlap(prompt_tokens, text)
    if score >= HIGH_OVERLAP and len(shared) >= 2:
        return ResourceMatch(name=name, path=path, confidence="high", matched_terms=shared)
    if score >= MEDIUM_OVERLAP and len(shared) >= 2:
        return ResourceMatch(name=name, path=path, confidence="medium", matched_terms=shared)
    return None


def match_skills(prompt: str, skills: list[SkillInfo]) -> ResourceMatch | None:
    prompt_tokens = tokenize(prompt)
    best: ResourceMatch | None = None
    for skill in skills:
        match = _best_match(prompt_tokens, skill.name, skill.path,
                             f"{skill.name} {skill.description}")
        if match and (best is None or _rank(match) > _rank(best)):
            best = match
    return best


def match_agents(prompt: str, agents: list[AgentInfo]) -> ResourceMatch | None:
    prompt_tokens = tokenize(prompt)
    best: ResourceMatch | None = None
    for agent in agents:
        match = _best_match(prompt_tokens, agent.name, agent.path,
                             f"{agent.name} {agent.description}")
        if match and (best is None or _rank(match) > _rank(best)):
            best = match
    return best


def match_claude_md(prompt: str, claude_mds: list[ClaudeMdInfo]) -> ResourceMatch | None:
    """Flag likely duplication between a prompt and an existing CLAUDE.md rule.

    Conservative on purpose: requires a longer prompt and a much higher
    overlap ratio than Skill/Agent matching, since restating part of a
    project rule in a prompt is normal and shouldn't be nagged about.
    """
    if len(prompt.split()) < CLAUDE_MD_MIN_PROMPT_WORDS:
        return None

    prompt_tokens = tokenize(prompt)
    best: ResourceMatch | None = None
    for doc in claude_mds:
        if not doc.preview:
            continue
        for line in doc.preview.splitlines():
            line = line.strip("-*# \t")
            if len(line.split()) < CLAUDE_MD_MIN_PROMPT_WORDS:
                continue
            line_tokens = tokenize(line)
            if not line_tokens:
                continue
            shared = prompt_tokens & line_tokens
            ratio = len(shared) / len(line_tokens)
            if ratio >= CLAUDE_MD_OVERLAP_THRESHOLD and len(shared) >= 3:
                match = ResourceMatch(name=line[:100], path=doc.path,
                                       confidence="medium", matched_terms=sorted(shared))
                if best is None or len(match.matched_terms) > len(best.matched_terms):
                    best = match
    return best


def _rank(match: ResourceMatch) -> int:
    return {"high": 2, "medium": 1}.get(match.confidence, 0)


def build_environment_feedback(
    prompt: str,
    analysis: AnalysisResult,
    skills: list[SkillInfo],
    agents: list[AgentInfo],
    claude_mds: list[ClaudeMdInfo],
) -> EnvironmentFeedback:
    """Combine a prompt's own analysis with what's actually detected on disk."""
    has_inferred_skill = any(o.kind == "skill" for o in analysis.opportunities)
    has_inferred_agent = any(o.kind == "agent" for o in analysis.opportunities)

    skill_match = match_skills(prompt, skills)
    if skill_match:
        skill_state = "existing"
    elif has_inferred_skill:
        skill_state = "candidate"
    else:
        skill_state = "none"

    agent_match = match_agents(prompt, agents)
    if agent_match:
        agent_state = "existing"
    elif has_inferred_agent:
        agent_state = "candidate"
    else:
        agent_state = "none"

    claude_md_match = match_claude_md(prompt, claude_mds)

    return EnvironmentFeedback(
        skill_state=skill_state,
        skill_match=skill_match,
        skill_candidate_message=(
            "Repeated workflow detected. No matching Skill detected — consider creating one."
            if skill_state == "candidate" else ""
        ),
        agent_state=agent_state,
        agent_match=agent_match,
        agent_candidate_message=(
            "This task looks suitable for independent delegation."
            if agent_state == "candidate" else ""
        ),
        claude_md_duplicate=claude_md_match,
    )
