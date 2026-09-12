"""Workshop 2.0 progress/quiz engine — pure Python, no Qt, so it's testable
the same way ``analyzer``/``analytics`` are. Persistence goes through the
existing local SQLite settings store (``database.get_setting``/
``set_setting``); nothing here ever makes a network call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from claude_code_coach import database as db

from .curriculum import ALL_LESSONS, LEVELS
from .models import Lesson, Level

_PROGRESS_SETTING_KEY = "workshop_progress_v1"


class WorkshopProgress:
    """In-memory progress state. Round-trips to/from a plain dict so it can
    be stored as one JSON blob under a single settings key — no schema
    migration needed for a feature this self-contained."""

    def __init__(self, data: dict | None = None):
        data = data or {}
        self.completed_lessons: set[str] = set(data.get("completed_lessons", []))
        self.quiz_scores: dict[str, dict] = dict(data.get("quiz_scores", {}))
        self.current_lesson_id: str | None = data.get("current_lesson_id")
        self.completion_date: str | None = data.get("completion_date")

    def to_dict(self) -> dict:
        return {
            "completed_lessons": sorted(self.completed_lessons),
            "quiz_scores": self.quiz_scores,
            "current_lesson_id": self.current_lesson_id,
            "completion_date": self.completion_date,
        }

    def is_complete(self, lesson_id: str) -> bool:
        return lesson_id in self.completed_lessons

    def mark_complete(self, lesson_id: str) -> None:
        self.completed_lessons.add(lesson_id)

    def record_quiz(self, lesson_id: str, correct: int, total: int) -> None:
        self.quiz_scores[lesson_id] = {
            "correct": correct,
            "total": total,
            "completed_on": datetime.now().isoformat(timespec="seconds"),
        }


# -- persistence -------------------------------------------------------
def load_progress() -> WorkshopProgress:
    raw = db.get_setting(_PROGRESS_SETTING_KEY)
    if not raw:
        return WorkshopProgress()
    try:
        return WorkshopProgress(json.loads(raw))
    except (ValueError, TypeError):
        # Corrupt/unreadable local state should never crash the app —
        # just start the learner over rather than blow up Workshop Mode.
        return WorkshopProgress()


def save_progress(progress: WorkshopProgress) -> None:
    db.set_setting(_PROGRESS_SETTING_KEY, json.dumps(progress.to_dict()))


# -- navigation ----------------------------------------------------------
def lesson_by_id(lesson_id: str) -> Lesson | None:
    for lesson in ALL_LESSONS:
        if lesson.id == lesson_id:
            return lesson
    return None


def level_for_lesson(lesson_id: str) -> Level | None:
    for level in LEVELS:
        if any(lesson.id == lesson_id for lesson in level.lessons):
            return level
    return None


def first_lesson_id() -> str:
    return ALL_LESSONS[0].id


def next_lesson_id(lesson_id: str) -> str | None:
    ids = [l.id for l in ALL_LESSONS]
    try:
        i = ids.index(lesson_id)
    except ValueError:
        return None
    return ids[i + 1] if i + 1 < len(ids) else None


def previous_lesson_id(lesson_id: str) -> str | None:
    ids = [l.id for l in ALL_LESSONS]
    try:
        i = ids.index(lesson_id)
    except ValueError:
        return None
    return ids[i - 1] if i > 0 else None


def first_incomplete_lesson_id(progress: WorkshopProgress) -> str:
    for lesson in ALL_LESSONS:
        if not progress.is_complete(lesson.id):
            return lesson.id
    return ALL_LESSONS[-1].id


def resume_lesson_id(progress: WorkshopProgress) -> str:
    """Where the learner should land on opening Workshop Mode: their last
    lesson if it's a real, current lesson id, otherwise the first
    incomplete one (or the very first lesson for a brand-new learner)."""
    if progress.current_lesson_id and lesson_by_id(progress.current_lesson_id):
        return progress.current_lesson_id
    return first_incomplete_lesson_id(progress)


# -- quiz scoring ----------------------------------------------------------
def score_quiz(lesson: Lesson, answers: dict[int, int]) -> tuple[int, int]:
    """``answers`` maps question index -> chosen option index. Returns
    (correct, total)."""
    correct = 0
    for i, question in enumerate(lesson.quiz):
        if answers.get(i) == question.correct_index():
            correct += 1
    return correct, len(lesson.quiz)


# -- level status / progress summary --------------------------------------
def level_progress(level: Level, progress: WorkshopProgress) -> tuple[int, int]:
    done = sum(1 for lesson in level.lessons if progress.is_complete(lesson.id))
    return done, len(level.lessons)


def level_status(level: Level, progress: WorkshopProgress) -> str:
    """"done" | "current" | "upcoming" — used to render the ✓ / → / ○
    course-map glyphs. Nothing is ever hard-locked: a learner can always
    jump ahead, this only affects the glyph shown."""
    done, total = level_progress(level, progress)
    if done == total and total > 0:
        return "done"
    if done > 0:
        return "current"
    return "upcoming"


def percent_complete(progress: WorkshopProgress) -> int:
    if not ALL_LESSONS:
        return 0
    return round(100 * len(progress.completed_lessons) / len(ALL_LESSONS))


def is_course_complete(progress: WorkshopProgress) -> bool:
    return all(lesson.id in progress.completed_lessons for lesson in ALL_LESSONS)


@dataclass
class CompletionSummary:
    modules_completed: int
    modules_total: int
    quiz_correct: int
    quiz_total: int
    complete: bool
    score_pct: int | None
    recommended_next: tuple[str, ...]  # lesson ids worth reviewing


def completion_summary(progress: WorkshopProgress) -> CompletionSummary:
    quiz_correct = sum(v.get("correct", 0) for v in progress.quiz_scores.values())
    quiz_total = sum(v.get("total", 0) for v in progress.quiz_scores.values())
    score_pct = round(100 * quiz_correct / quiz_total) if quiz_total else None

    # Lessons whose quiz was attempted but not answered perfectly — a
    # natural, non-arbitrary "recommended review" list rather than a
    # fabricated one.
    recommended = tuple(
        lesson_id
        for lesson_id, score in progress.quiz_scores.items()
        if score.get("total", 0) and score.get("correct", 0) < score.get("total", 0)
    )

    return CompletionSummary(
        modules_completed=len(progress.completed_lessons),
        modules_total=len(ALL_LESSONS),
        quiz_correct=quiz_correct,
        quiz_total=quiz_total,
        complete=is_course_complete(progress),
        score_pct=score_pct,
        recommended_next=recommended,
    )


def mark_completion_date_if_newly_complete(progress: WorkshopProgress) -> None:
    if is_course_complete(progress) and not progress.completion_date:
        progress.completion_date = datetime.now().date().isoformat()
