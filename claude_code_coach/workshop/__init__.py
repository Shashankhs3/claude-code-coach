"""Workshop 2.0: the structured Claude Code training curriculum plus its
progress/quiz engine — plain data and pure functions, no Qt. See
``curriculum/`` for lesson content and ``engine.py`` for progress state,
navigation, and scoring. The UI that renders this lives in
``ui/workshop.py``."""

from .curriculum import ALL_LESSONS, LEVELS, validate_curriculum
from .models import Lesson, Level, QuizOption, QuizQuestion, SourceRef, SourceType, TryIt

__all__ = [
    "ALL_LESSONS",
    "LEVELS",
    "validate_curriculum",
    "Lesson",
    "Level",
    "QuizOption",
    "QuizQuestion",
    "SourceRef",
    "SourceType",
    "TryIt",
]
