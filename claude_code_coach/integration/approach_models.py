"""Typed model for the Approach Advisor (spec Feature 2)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ApproachRecommendation:
    kind: str          # "skill_existing" | "skill_candidate" | "agent_existing" |
                        # "agent_candidate" | "claude_md" | "mcp_relevant" |
                        # "parallel_work" | "verification_missing" | "verification_done" |
                        # "context_noisy" | "context_coherent" | "normal_session"
    level: str          # "low" | "medium" | "high"
    icon: str
    message: str
    what_happened: str = ""
    why_it_matters: str = ""
    try_instead: str = ""
    evidence: dict = field(default_factory=dict)


@dataclass
class ApproachReport:
    recommendations: list[ApproachRecommendation] = field(default_factory=list)

    def top(self, n: int = 3) -> list[ApproachRecommendation]:
        order = {"high": 0, "medium": 1, "low": 2}
        return sorted(self.recommendations, key=lambda r: order.get(r.level, 3))[:n]
