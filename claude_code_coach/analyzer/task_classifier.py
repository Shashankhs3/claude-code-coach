"""Task-type classification.

The same missing information means different things depending on what kind
of request this is (see spec section 5). Classifying the task first lets the
dimension analyzers and scorer decide which dimensions actually matter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from . import lexicon as lex


class TaskType(str, Enum):
    INFORMATION = "information"
    EXPLANATION = "explanation"
    INVESTIGATION = "investigation"
    DEBUGGING = "debugging"
    IMPLEMENTATION = "implementation"
    REFACTORING = "refactoring"
    REVIEW = "review"
    SECURITY_REVIEW = "security_review"
    RESEARCH = "research"
    REPETITIVE_WORKFLOW = "repetitive_workflow"
    MIXED = "mixed"

    @property
    def label(self) -> str:
        return {
            TaskType.INFORMATION: "Information request",
            TaskType.EXPLANATION: "Explanation request",
            TaskType.INVESTIGATION: "Investigation",
            TaskType.DEBUGGING: "Debugging",
            TaskType.IMPLEMENTATION: "Implementation",
            TaskType.REFACTORING: "Refactoring",
            TaskType.REVIEW: "Review",
            TaskType.SECURITY_REVIEW: "Security review",
            TaskType.RESEARCH: "Research",
            TaskType.REPETITIVE_WORKFLOW: "Repetitive workflow",
            TaskType.MIXED: "Mixed",
        }[self]


@dataclass
class TaskClassification:
    primary: TaskType
    signals: dict[str, bool] = field(default_factory=dict)

    @property
    def informational(self) -> bool:
        return self.primary in (TaskType.INFORMATION, TaskType.EXPLANATION)

    @property
    def implementation_like(self) -> bool:
        return self.primary in (
            TaskType.IMPLEMENTATION,
            TaskType.REFACTORING,
            TaskType.DEBUGGING,
        )

    @property
    def investigative(self) -> bool:
        return self.primary in (TaskType.INVESTIGATION, TaskType.DEBUGGING)

    @property
    def review_like(self) -> bool:
        return self.primary in (
            TaskType.REVIEW,
            TaskType.SECURITY_REVIEW,
            TaskType.REPETITIVE_WORKFLOW,
        )


def classify(prompt: str) -> TaskClassification:
    p = prompt.strip()
    low = p.lower()

    question_like = bool(lex.QUESTION_START.search(low)) or p.endswith("?")
    info_imperative = bool(lex.INFO_IMPERATIVE_START.search(low))
    question_like = question_like or info_imperative
    low_for_action = lex.NEGATED_ACTION.sub(" ", low)
    action = bool(lex.ACTION_VERBS.search(low_for_action))
    explain = bool(lex.EXPLAIN_VERBS.search(low))
    investigate = bool(lex.INVESTIGATE_VERBS.search(low))
    debug = bool(lex.DEBUG_SIGNALS.search(low))
    implement = bool(lex.IMPLEMENT_SIGNALS.search(low))
    refactor = bool(lex.REFACTOR_SIGNALS.search(low))
    review = bool(lex.REVIEW_SIGNALS.search(low))
    security = bool(lex.SECURITY_SIGNALS.search(low))
    research = bool(lex.RESEARCH_SIGNALS.search(low))
    repetitive_trigger = bool(lex.REPETITIVE_TRIGGER.search(low))
    checklist_steps = len(lex.CHECKLIST_STEP_WORDS.findall(low))

    signals = {
        "question_like": question_like,
        "action": action,
        "explain": explain,
        "investigate": investigate,
        "debug": debug,
        "implement": implement,
        "refactor": refactor,
        "review": review,
        "security": security,
        "research": research,
        "repetitive_trigger": repetitive_trigger,
        "checklist_steps": checklist_steps >= 2,
    }

    informational = question_like and not action

    # Priority order: most specific/composite signals first.
    if repetitive_trigger and (review or checklist_steps >= 2):
        primary = TaskType.REPETITIVE_WORKFLOW
    elif security and review:
        primary = TaskType.SECURITY_REVIEW
    elif debug and (action or investigate):
        primary = TaskType.DEBUGGING
    elif investigate:
        primary = TaskType.INVESTIGATION
    elif refactor:
        primary = TaskType.REFACTORING
    elif review:
        primary = TaskType.REVIEW
    elif research and not action:
        primary = TaskType.RESEARCH
    elif implement or (action and not informational):
        primary = TaskType.IMPLEMENTATION
    elif explain and not action:
        primary = TaskType.EXPLANATION
    elif informational:
        primary = TaskType.INFORMATION
    else:
        primary = TaskType.MIXED

    # If many distinct strong signal groups fire at once, treat as mixed
    # unless it already resolved to a clean composite type.
    strong_groups = sum(
        [debug, implement, refactor, review, research, investigate, explain]
    )
    if strong_groups >= 3 and primary not in (
        TaskType.SECURITY_REVIEW,
        TaskType.REPETITIVE_WORKFLOW,
    ):
        primary = TaskType.MIXED

    return TaskClassification(primary=primary, signals=signals)
