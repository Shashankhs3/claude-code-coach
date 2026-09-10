"""Shared data types for the analyzer package."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

DimensionStatus = Literal["clear", "partial", "missing", "na"]
Confidence = Literal["low", "medium", "high"]
OpportunityKind = Literal["skill", "agent", "claude_md", "context", "search_first"]

DIMENSION_NAMES = (
    "goal",
    "scope",
    "investigation",
    "constraints",
    "done",
    "output",
)


@dataclass
class DimensionResult:
    status: DimensionStatus
    detail: str = ""

    @property
    def applicable(self) -> bool:
        return self.status != "na"


@dataclass
class Opportunity:
    kind: OpportunityKind
    message: str
    confidence: Confidence = "low"
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "message": self.message,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass
class AnalysisResult:
    prompt: str
    task_type: str
    dimensions: dict[str, DimensionResult]
    score: int
    rating: str
    good: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    opportunities: list[Opportunity] = field(default_factory=list)
    breadth_level: int = 0
    vague_goal: bool = False
    context_note: str = ""

    def dimension_status(self, name: str) -> str:
        dim = self.dimensions.get(name)
        return dim.status if dim else "na"

    def to_row(self) -> dict:
        """Serialize for database storage (see database.db.insert_prompt)."""
        return {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "prompt": self.prompt,
            "score": self.score,
            "rating": self.rating,
            "task_type": self.task_type,
            "goal_status": self.dimension_status("goal"),
            "scope_status": self.dimension_status("scope"),
            "investigation_status": self.dimension_status("investigation"),
            "constraints_status": self.dimension_status("constraints"),
            "done_status": self.dimension_status("done"),
            "output_status": self.dimension_status("output"),
            "good": self.good,
            "warnings": self.warnings,
            "opportunities": [o.to_dict() for o in self.opportunities],
            "breadth_level": self.breadth_level,
            "context_flag": self.context_note,
        }
