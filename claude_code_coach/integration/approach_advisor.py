"""Recommended Approach (spec Feature 2): "for this task, how should I work
with Claude Code?" — synthesizes all three independent evidence sources
(spec section 33): the prompt itself, the real scanned environment, and (if
available) the live runtime session. Never collapsed into one score;
each recommendation stands on its own evidence.
"""

from __future__ import annotations

from ..analyzer.models import AnalysisResult
from ..analyzer.prompt_extractor import extract
from ..providers.models import EnvironmentSnapshot
from ..runtime.models import RuntimeStatus
from .approach_models import ApproachReport, ApproachRecommendation
from .environment_matching import build_environment_feedback

_MIN_INDEPENDENT_AREAS = 3


def recommend_approach(
    prompt: str,
    analysis: AnalysisResult,
    environment_snapshot: EnvironmentSnapshot | None = None,
    runtime_status: RuntimeStatus | None = None,
) -> ApproachReport:
    recs: list[ApproachRecommendation] = []

    skills = environment_snapshot.skills if environment_snapshot else []
    agents = environment_snapshot.agents if environment_snapshot else []
    claude_mds = environment_snapshot.claude_md if environment_snapshot else []
    mcp_servers = environment_snapshot.mcp_servers if environment_snapshot else []

    fb = build_environment_feedback(prompt, analysis, skills, agents, claude_mds)

    if fb.skill_state == "existing":
        recs.append(ApproachRecommendation(
            # Level reflects the match's actual confidence, not a fixed
            # value — a "medium confidence" match shouldn't outrank a
            # "high confidence" match on a different resource.
            kind="skill_existing", level=fb.skill_match.confidence, icon="✓",
            message=f"Use the existing '{fb.skill_match.name}' Skill instead of a "
                    f"normal session.",
            why_it_matters="A matching Skill already encodes this workflow consistently.",
            evidence={"skill": fb.skill_match.name, "confidence": fb.skill_match.confidence,
                      "matched_terms": fb.skill_match.matched_terms},
        ))
    elif fb.skill_state == "candidate":
        recs.append(ApproachRecommendation(
            kind="skill_candidate", level="medium", icon="🔧",
            message=fb.skill_candidate_message or "Repeated workflow detected. "
                    "No matching Skill detected — consider creating one.",
        ))

    if fb.agent_state == "existing":
        recs.append(ApproachRecommendation(
            kind="agent_existing", level=fb.agent_match.confidence, icon="🤖",
            message=f"Existing '{fb.agent_match.name}' Agent may be relevant.",
            evidence={"agent": fb.agent_match.name, "confidence": fb.agent_match.confidence},
        ))
    elif fb.agent_state == "candidate":
        recs.append(ApproachRecommendation(
            kind="agent_candidate", level="low", icon="🤖",
            message=fb.agent_candidate_message or "This task looks suitable for "
                    "independent delegation.",
        ))

    if fb.claude_md_duplicate:
        recs.append(ApproachRecommendation(
            kind="claude_md", level="low", icon="📝",
            message="This may already be covered by an existing CLAUDE.md instruction.",
            evidence={"path": fb.claude_md_duplicate.path},
        ))

    if mcp_servers:
        from ..analytics.patterns import tokenize
        prompt_tokens = tokenize(prompt)
        for mcp in mcp_servers:
            if tokenize(mcp.name) & prompt_tokens:
                recs.append(ApproachRecommendation(
                    kind="mcp_relevant", level="low", icon="🔌",
                    message=f"The '{mcp.name}' MCP server might be relevant here.",
                    why_it_matters="MCP servers can provide external capabilities beyond "
                                   "file edits — worth checking before doing it manually.",
                    evidence={"server": mcp.name},
                ))
                break  # conservative: surface at most one guess, not a name-matching sweep

    extraction = extract(prompt)
    if len(extraction.independent_areas) >= _MIN_INDEPENDENT_AREAS and not extraction.has_sequential_connector:
        recs.append(ApproachRecommendation(
            kind="parallel_work", level="medium", icon="🔀",
            message="Independent work detected across multiple areas.",
            what_happened=f"This task spans: {', '.join(extraction.independent_areas[:4])}.",
            why_it_matters="Independent workstreams can be investigated separately "
                           "without one blocking another.",
            try_instead="Consider parallel sessions or delegating each area "
                        "independently (e.g. to an Agent).",
            evidence={"areas": extraction.independent_areas},
        ))

    if runtime_status and runtime_status.current_session:
        for sig in runtime_status.signals:
            if sig.kind in ("verification_missing", "verification_done",
                             "context_noisy", "context_coherent"):
                icon = {"verification_missing": "⚠", "verification_done": "✓",
                        "context_noisy": "⚠", "context_coherent": "✓"}[sig.kind]
                recs.append(ApproachRecommendation(
                    kind=sig.kind, level=sig.level, icon=icon, message=sig.message,
                    what_happened=sig.what_happened, why_it_matters=sig.why_it_matters,
                    try_instead=sig.try_instead, evidence=sig.evidence,
                ))

    if not recs:
        recs.append(ApproachRecommendation(
            kind="normal_session", level="low", icon="•",
            message="A normal Claude Code session/prompt looks appropriate here.",
        ))

    return ApproachReport(recommendations=recs)
