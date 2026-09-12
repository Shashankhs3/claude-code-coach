"""Assembles the full Workshop 2.0 curriculum from its per-theme modules
(spec: "Do NOT hardcode the entire curriculum into one giant UI file") and
validates it structurally — every lesson has a source, an objective, a
takeaway, a well-formed quiz, and (if it names one) a real Coach nav page.

Each theme module below owns a handful of adjacent levels; splitting by
theme rather than by single level keeps the file count manageable while
still separating content by concern, matching how the rest of this
project organizes modules (one file per cohesive concern, not one per
tiny unit)."""

from __future__ import annotations

from ..models import Level, Lesson, SourceType
from .automation_safety import LEVEL_10, LEVEL_11, LEVEL_12
from .context_control import LEVEL_2, LEVEL_3, LEVEL_4
from .delegation import LEVEL_7, LEVEL_8, LEVEL_9
from .exam import LEVEL_20
from .orientation import LEVEL_0, LEVEL_1
from .practice import LEVEL_17, LEVEL_18, LEVEL_19
from .project_memory import LEVEL_5, LEVEL_6
from .strategy import LEVEL_13, LEVEL_14, LEVEL_15, LEVEL_16

LEVELS: tuple[Level, ...] = (
    LEVEL_0, LEVEL_1, LEVEL_2, LEVEL_3, LEVEL_4, LEVEL_5, LEVEL_6, LEVEL_7,
    LEVEL_8, LEVEL_9, LEVEL_10, LEVEL_11, LEVEL_12, LEVEL_13, LEVEL_14,
    LEVEL_15, LEVEL_16, LEVEL_17, LEVEL_18, LEVEL_19, LEVEL_20,
)

ALL_LESSONS: tuple[Lesson, ...] = tuple(
    lesson for level in LEVELS for lesson in level.lessons
)

# Nav labels a Lesson.try_it may point at — kept in sync with
# ui.main_window.PAGES by a test (tests/test_workshop.py), not imported
# directly here to avoid a ui -> workshop -> ui import cycle.
KNOWN_COACH_PAGES = frozenset({
    "Dashboard", "Prompt Inspector", "Approach Advisor", "Sessions",
    "Prompt History", "Context", "Skills", "Skill Creator", "Agents",
    "Agent Creator", "Integrations", "Environment", "Habits", "Usage",
    "Workshop Mode", "Settings",
})

# Slash commands this curriculum is allowed to name — every one has been
# checked against current Claude Code documentation (see sources.py). A
# lesson naming any other "/command" fails curriculum validation, so an
# invented or deprecated command can't quietly ship (spec: "no lesson
# claims unsupported commands/features").
KNOWN_SLASH_COMMANDS = frozenset({
    "/clear", "/compact", "/init", "/rewind", "/hooks", "/permissions",
    "/sandbox", "/plugin", "/context", "/doctor", "/goal", "/batch",
    "/btw", "/code-review", "/skill-name", "/verify", "/fix-issue",
})


def validate_curriculum() -> list[str]:
    """Returns a list of problems (empty = curriculum is well-formed).
    Used both by tests/test_workshop.py and available for a future
    content-refresh pass to re-run before shipping updated lessons."""
    import re

    problems: list[str] = []
    seen_ids: set[str] = set()

    for level in LEVELS:
        if not level.lessons:
            problems.append(f"Level {level.id} ({level.title}) has no lessons")
        for lesson in level.lessons:
            if lesson.id in seen_ids:
                problems.append(f"Duplicate lesson id: {lesson.id}")
            seen_ids.add(lesson.id)

            if not lesson.objective.strip():
                problems.append(f"{lesson.id}: missing learning objective")
            if not lesson.takeaway.strip():
                problems.append(f"{lesson.id}: missing takeaway")
            if not lesson.sources:
                problems.append(f"{lesson.id}: no source attached")
            for src in lesson.sources:
                if not isinstance(src.source_type, SourceType):
                    problems.append(f"{lesson.id}: source has an invalid source_type")
                if not src.title.strip():
                    problems.append(f"{lesson.id}: source missing a title")

            if lesson.quiz:
                for qi, question in enumerate(lesson.quiz):
                    try:
                        question.correct_index()
                    except ValueError:
                        problems.append(
                            f"{lesson.id}: quiz question {qi} has no answer key"
                        )
                    if not question.explanation.strip():
                        problems.append(
                            f"{lesson.id}: quiz question {qi} has no explanation"
                        )
                    n_correct = sum(1 for o in question.options if o.correct)
                    if n_correct != 1:
                        problems.append(
                            f"{lesson.id}: quiz question {qi} has {n_correct} correct "
                            "options (must be exactly 1)"
                        )

            if lesson.try_it and lesson.try_it.related_page:
                if lesson.try_it.related_page not in KNOWN_COACH_PAGES:
                    problems.append(
                        f"{lesson.id}: try_it references unknown Coach page "
                        f"{lesson.try_it.related_page!r}"
                    )

            # Every /command mentioned anywhere in this lesson's learner-visible
            # text — including its title, objective, and quiz content, not just
            # the main body — must be on the verified allow-list above.
            text_parts = [
                lesson.title, lesson.objective, lesson.what, lesson.why,
                lesson.example, lesson.bad_approach, lesson.better_approach,
                lesson.takeaway,
            ]
            for question in lesson.quiz:
                text_parts.append(question.prompt)
                text_parts.append(question.explanation)
                text_parts.extend(o.text for o in question.options)
            full_text = " ".join(text_parts)
            for match in re.finditer(r"(?<!\w)/[a-zA-Z][\w-]*", full_text):
                command = match.group(0)
                if command not in KNOWN_SLASH_COMMANDS:
                    problems.append(
                        f"{lesson.id}: mentions unverified command {command!r} "
                        "— add it to KNOWN_SLASH_COMMANDS only after checking current docs"
                    )

    return problems
