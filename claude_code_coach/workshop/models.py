"""Data model for Workshop Mode's curriculum (Workshop 2.0).

Plain dataclasses only — no Qt, no database access — so the curriculum can
be loaded, validated, and tested independently of the UI, the same way
``analyzer`` and ``analytics`` are. See ``curriculum/`` for the actual
lesson content and ``engine.py`` for progress/quiz logic built on top of
these types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SourceType(str, Enum):
    """The four labels every lesson must use to mark where its content
    comes from (spec: "Source hierarchy") — never blur these together."""

    OFFICIAL_ANTHROPIC = "official_anthropic"
    CLAUDE_CODE_DOCUMENTED = "claude_code_documented"
    COMMUNITY_PRACTICE = "community_practice"
    COACH_HEURISTIC = "coach_heuristic"


SOURCE_LABELS: dict[SourceType, str] = {
    SourceType.OFFICIAL_ANTHROPIC: "Official Anthropic",
    SourceType.CLAUDE_CODE_DOCUMENTED: "Claude Code documented",
    SourceType.COMMUNITY_PRACTICE: "Community practice",
    SourceType.COACH_HEURISTIC: "Coach heuristic",
}


@dataclass(frozen=True)
class SourceRef:
    """One citation attached to a lesson. ``url``/``verified_on`` are
    metadata for a future content-refresh pass (spec: "Search / update") —
    the running app never fetches them, and the UI never dumps the raw URL,
    it shows ``title`` as a small clickable reference."""

    source_type: SourceType
    title: str
    url: str = ""
    verified_on: str = ""
    note: str = ""

    @property
    def label(self) -> str:
        return SOURCE_LABELS[self.source_type]


@dataclass(frozen=True)
class QuizOption:
    text: str
    correct: bool = False


@dataclass(frozen=True)
class QuizQuestion:
    prompt: str
    options: tuple[QuizOption, ...]
    explanation: str

    def correct_index(self) -> int:
        for i, opt in enumerate(self.options):
            if opt.correct:
                return i
        raise ValueError(f"quiz question has no correct option: {self.prompt!r}")


@dataclass(frozen=True)
class TryIt:
    """A hands-on interaction. ``related_page`` is a nav label from
    ``ui.main_window.PAGES`` the learner can jump to directly — validated
    against the real nav list in tests, not just assumed correct."""

    instructions: str
    related_page: str | None = None
    action_label: str = "Open in the Coach"


@dataclass(frozen=True)
class Lesson:
    id: str
    title: str
    objective: str
    what: str
    why: str = ""
    example: str = ""
    bad_approach: str = ""
    better_approach: str = ""
    try_it: TryIt | None = None
    quiz: tuple[QuizQuestion, ...] = ()
    takeaway: str = ""
    sources: tuple[SourceRef, ...] = ()
    # Fraction of quiz questions that must be correct to count this lesson
    # complete. Every ordinary lesson requires all of its (usually 1-2)
    # questions; the final exam (many questions) uses a lower bar.
    passing_ratio: float = 1.0
    # Optional tag naming a bespoke interactive widget the UI renders for
    # this lesson (e.g. "prompt_lab", "context_meter", "decision_wizard").
    # Empty for the common case of a standard What/Why/Example/Quiz lesson.
    interactive: str = ""

    def passes(self, correct: int, total: int) -> bool:
        if total == 0:
            return True
        return (correct / total) >= self.passing_ratio


@dataclass(frozen=True)
class Level:
    id: str
    title: str
    lessons: tuple[Lesson, ...] = field(default_factory=tuple)
