"""Context Efficiency Score calculation.

This is a local coaching heuristic. It is never described as an official
Anthropic/Claude metric and never claims to measure actual token savings.
"""

from __future__ import annotations

from .models import DimensionResult
from .task_classifier import TaskType

# Per-task-type dimension weights. Only dimensions listed for a task type are
# scored for it — the rest are "not applicable" and neither help nor hurt.
# Each row sums to 100.
WEIGHTS: dict[TaskType, dict[str, int]] = {
    TaskType.INFORMATION: {"goal": 55, "scope": 15, "investigation": 10, "output": 20},
    TaskType.EXPLANATION: {"goal": 55, "scope": 10, "output": 35},
    TaskType.INVESTIGATION: {
        "goal": 30, "scope": 10, "investigation": 30, "constraints": 5,
        "done": 15, "output": 10,
    },
    TaskType.DEBUGGING: {
        "goal": 20, "scope": 15, "investigation": 25, "constraints": 10,
        "done": 20, "output": 10,
    },
    TaskType.IMPLEMENTATION: {
        "goal": 20, "scope": 20, "investigation": 10, "constraints": 15,
        "done": 25, "output": 10,
    },
    TaskType.REFACTORING: {
        "goal": 20, "scope": 20, "investigation": 5, "constraints": 25,
        "done": 20, "output": 10,
    },
    TaskType.REVIEW: {
        "goal": 20, "scope": 20, "investigation": 10, "constraints": 10,
        "done": 10, "output": 30,
    },
    TaskType.SECURITY_REVIEW: {
        "goal": 15, "scope": 20, "investigation": 10, "constraints": 15,
        "done": 10, "output": 30,
    },
    TaskType.RESEARCH: {
        "goal": 30, "scope": 10, "investigation": 20, "done": 10, "output": 30,
    },
    TaskType.REPETITIVE_WORKFLOW: {
        "goal": 15, "scope": 15, "investigation": 10, "constraints": 10,
        "done": 15, "output": 35,
    },
    TaskType.MIXED: {
        "goal": 20, "scope": 15, "investigation": 15, "constraints": 15,
        "done": 20, "output": 15,
    },
}

_STATUS_FRACTION = {"clear": 1.0, "partial": 0.6, "missing": 0.0, "na": 1.0}

# Fixed baseline used for prompts that are vague/low-effort at the goal
# level (e.g. "Fix my project.") or ask to read everything then fix
# everything. Keeps these reliably in the POOR band regardless of which
# other dimensions happen to match.
_LOW_EFFORT_BASE = 20
_LOW_EFFORT_MIN = 10
_LOW_EFFORT_MAX = 30


def bucket(score: int) -> str:
    if score >= 90:
        return "EXCELLENT"
    if score >= 75:
        return "GOOD"
    if score >= 50:
        return "NEEDS IMPROVEMENT"
    return "POOR"


def score_prompt(
    task_type: TaskType,
    dimensions: dict[str, DimensionResult],
    *,
    breadth_level: int,
    overly_broad_read: bool,
    low_effort: bool,
) -> tuple[int, str]:
    if low_effort:
        score = _LOW_EFFORT_BASE
        if dimensions.get("scope", DimensionResult("na")).status == "clear":
            score += 5
        if dimensions.get("output", DimensionResult("na")).status == "clear":
            score += 3
        score = max(_LOW_EFFORT_MIN, min(_LOW_EFFORT_MAX, score))
        return score, bucket(score)

    weights = WEIGHTS.get(task_type, WEIGHTS[TaskType.MIXED])
    total = 0.0
    for dim_name, weight in weights.items():
        dim = dimensions.get(dim_name)
        status = dim.status if dim else "na"
        total += weight * _STATUS_FRACTION.get(status, 0.0)

    score = total

    if overly_broad_read:
        score -= 12
    if breadth_level >= 2:
        score -= 10

    score = int(round(max(0, min(100, score))))
    return score, bucket(score)
