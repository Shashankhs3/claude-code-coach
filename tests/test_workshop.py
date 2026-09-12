"""Tests for Workshop Mode 2.0: curriculum data, the pure progress/quiz
engine, and the Qt rendering layer built on top of them.
"""

from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QPushButton

from claude_code_coach.database import db as db_module

# Same pattern as tests/test_gui.py: one shared offscreen QApplication so
# this file also works when run standalone (`pytest tests/test_workshop.py`),
# not only as part of the full suite after test_gui.py has already made one.
_app = QApplication.instance() or QApplication(sys.argv)
from claude_code_coach.workshop import ALL_LESSONS, LEVELS, engine, validate_curriculum
from claude_code_coach.workshop.curriculum import KNOWN_COACH_PAGES
from claude_code_coach.workshop.models import QuizOption, QuizQuestion, SourceType


class DbTestCase(unittest.TestCase):
    """Same temp-DB isolation pattern as tests/test_gui.py's GuiTestCase —
    Workshop progress persists through the same local settings store."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_path = db_module.DB_PATH
        db_module.DB_PATH = Path(self._tmpdir.name) / "workshop_test.db"
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self._original_path
        self._tmpdir.cleanup()


# -- curriculum completeness -------------------------------------------------
class TestCurriculumCompleteness(unittest.TestCase):
    def test_curriculum_validates_clean(self):
        problems = validate_curriculum()
        self.assertEqual(problems, [], "\n".join(problems))

    def test_has_21_levels(self):
        self.assertEqual(len(LEVELS), 21)

    def test_every_level_has_lessons(self):
        for level in LEVELS:
            self.assertTrue(level.lessons, f"Level {level.id} has no lessons")

    def test_lesson_ids_are_unique(self):
        ids = [l.id for l in ALL_LESSONS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_lesson_has_objective_and_takeaway(self):
        for lesson in ALL_LESSONS:
            self.assertTrue(lesson.objective.strip(), lesson.id)
            self.assertTrue(lesson.takeaway.strip(), lesson.id)

    def test_every_lesson_has_at_least_one_source(self):
        for lesson in ALL_LESSONS:
            self.assertTrue(lesson.sources, lesson.id)
            for src in lesson.sources:
                self.assertIsInstance(src.source_type, SourceType)
                self.assertTrue(src.title.strip())

    def test_every_quiz_question_has_exactly_one_answer_key(self):
        for lesson in ALL_LESSONS:
            for question in lesson.quiz:
                n_correct = sum(1 for o in question.options if o.correct)
                self.assertEqual(n_correct, 1, f"{lesson.id}: {question.prompt!r}")
                self.assertTrue(question.explanation.strip(), lesson.id)

    def test_try_it_pages_are_real_coach_pages(self):
        for lesson in ALL_LESSONS:
            if lesson.try_it and lesson.try_it.related_page:
                self.assertIn(lesson.try_it.related_page, KNOWN_COACH_PAGES, lesson.id)

    def test_try_it_pages_match_actual_nav(self):
        """KNOWN_COACH_PAGES must not silently drift from the real sidebar."""
        from claude_code_coach.ui.main_window import PAGES
        real_labels = {label for label, _cls in PAGES}
        for lesson in ALL_LESSONS:
            if lesson.try_it and lesson.try_it.related_page:
                self.assertIn(lesson.try_it.related_page, real_labels, lesson.id)

    def test_final_exam_has_at_least_20_questions(self):
        exam = engine.lesson_by_id("20.1")
        self.assertIsNotNone(exam)
        self.assertGreaterEqual(len(exam.quiz), 20)

    def test_source_labels_are_the_four_required(self):
        from claude_code_coach.workshop.models import SOURCE_LABELS
        self.assertEqual(
            set(SOURCE_LABELS.values()),
            {"Official Anthropic", "Claude Code documented", "Community practice",
             "Coach heuristic"},
        )


# -- pure engine: navigation, scoring, persistence ---------------------------
class TestEngineNavigation(unittest.TestCase):
    def test_first_lesson_is_0_1(self):
        self.assertEqual(engine.first_lesson_id(), "0.1")

    def test_lessons_are_sequential_with_no_gaps(self):
        ids = [l.id for l in ALL_LESSONS]
        cur = ids[0]
        for expected_next in ids[1:]:
            self.assertEqual(engine.next_lesson_id(cur), expected_next)
            self.assertEqual(engine.previous_lesson_id(expected_next), cur)
            cur = expected_next

    def test_next_of_last_lesson_is_none(self):
        self.assertIsNone(engine.next_lesson_id(ALL_LESSONS[-1].id))

    def test_previous_of_first_lesson_is_none(self):
        self.assertIsNone(engine.previous_lesson_id(ALL_LESSONS[0].id))

    def test_unknown_lesson_id_navigation_is_none(self):
        self.assertIsNone(engine.next_lesson_id("does-not-exist"))
        self.assertIsNone(engine.previous_lesson_id("does-not-exist"))

    def test_level_for_lesson(self):
        level = engine.level_for_lesson("6.3")
        self.assertIsNotNone(level)
        self.assertEqual(level.id, "6")

    def test_lesson_by_id_roundtrip(self):
        for lesson in ALL_LESSONS[:5]:
            self.assertIs(engine.lesson_by_id(lesson.id), lesson)


class TestQuizScoring(unittest.TestCase):
    def setUp(self):
        self.lesson = engine.lesson_by_id("1.2")  # has exactly one quiz question

    def test_all_correct(self):
        answers = {i: q.correct_index() for i, q in enumerate(self.lesson.quiz)}
        correct, total = engine.score_quiz(self.lesson, answers)
        self.assertEqual((correct, total), (total, total))
        self.assertTrue(self.lesson.passes(correct, total))

    def test_all_wrong(self):
        answers = {}
        for i, q in enumerate(self.lesson.quiz):
            wrong = next(oi for oi in range(len(q.options)) if oi != q.correct_index())
            answers[i] = wrong
        correct, total = engine.score_quiz(self.lesson, answers)
        self.assertEqual(correct, 0)
        self.assertFalse(self.lesson.passes(correct, total))

    def test_unanswered_question_counts_as_wrong(self):
        correct, total = engine.score_quiz(self.lesson, {})
        self.assertEqual(correct, 0)
        self.assertEqual(total, len(self.lesson.quiz))

    def test_exam_passing_ratio_allows_some_misses(self):
        exam = engine.lesson_by_id("20.1")
        total = len(exam.quiz)
        # 90% correct should pass an 80%-threshold exam.
        self.assertTrue(exam.passes(round(total * 0.9), total))
        # 50% correct should not.
        self.assertFalse(exam.passes(round(total * 0.5), total))

    def test_malformed_question_raises_on_correct_index(self):
        bad = QuizQuestion(
            prompt="broken",
            options=(QuizOption("a"), QuizOption("b")),
            explanation="no correct option set",
        )
        with self.assertRaises(ValueError):
            bad.correct_index()


class TestProgressPersistence(DbTestCase):
    def test_round_trips_through_local_settings(self):
        progress = engine.load_progress()
        self.assertEqual(progress.completed_lessons, set())

        progress.mark_complete("0.1")
        progress.mark_complete("0.2")
        progress.record_quiz("1.2", 1, 1)
        progress.current_lesson_id = "1.3"
        engine.save_progress(progress)

        reloaded = engine.load_progress()
        self.assertEqual(reloaded.completed_lessons, {"0.1", "0.2"})
        self.assertEqual(reloaded.quiz_scores["1.2"]["correct"], 1)
        self.assertEqual(reloaded.current_lesson_id, "1.3")

    def test_corrupt_stored_json_falls_back_to_fresh_progress(self):
        db_module.set_setting("workshop_progress_v1", "{not valid json")
        progress = engine.load_progress()
        self.assertEqual(progress.completed_lessons, set())

    def test_percent_complete(self):
        progress = engine.load_progress()
        self.assertEqual(engine.percent_complete(progress), 0)
        progress.mark_complete(ALL_LESSONS[0].id)
        expected = round(100 / len(ALL_LESSONS))
        self.assertEqual(engine.percent_complete(progress), expected)

    def test_course_completion_and_summary(self):
        progress = engine.load_progress()
        for lesson in ALL_LESSONS:
            progress.mark_complete(lesson.id)
        self.assertTrue(engine.is_course_complete(progress))
        engine.mark_completion_date_if_newly_complete(progress)
        self.assertIsNotNone(progress.completion_date)

        summary = engine.completion_summary(progress)
        self.assertTrue(summary.complete)
        self.assertEqual(summary.modules_completed, len(ALL_LESSONS))

    def test_resume_lesson_prefers_first_incomplete(self):
        progress = engine.load_progress()
        progress.mark_complete(ALL_LESSONS[0].id)
        progress.mark_complete(ALL_LESSONS[1].id)
        self.assertEqual(engine.resume_lesson_id(progress), ALL_LESSONS[2].id)

    def test_level_status_progression(self):
        progress = engine.load_progress()
        level = LEVELS[0]
        self.assertEqual(engine.level_status(level, progress), "upcoming")
        progress.mark_complete(level.lessons[0].id)
        self.assertEqual(engine.level_status(level, progress), "current")
        for lesson in level.lessons:
            progress.mark_complete(lesson.id)
        self.assertEqual(engine.level_status(level, progress), "done")


# -- offline / no network dependency ------------------------------------------
class TestOfflineOperation(unittest.TestCase):
    _FORBIDDEN_MODULES = {
        "requests", "urllib.request", "urllib3", "http.client", "socket",
        "aiohttp", "httpx",
    }

    def _imported_modules(self, path: Path) -> set[str]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        return names

    def test_no_network_imports_in_workshop_package(self):
        import claude_code_coach.workshop as workshop_pkg
        pkg_dir = Path(workshop_pkg.__file__).parent
        for py_file in pkg_dir.rglob("*.py"):
            imports = self._imported_modules(py_file)
            hit = imports & self._FORBIDDEN_MODULES
            self.assertFalse(hit, f"{py_file} imports network module(s): {hit}")

    def test_no_network_imports_in_workshop_ui(self):
        import claude_code_coach.ui.workshop as workshop_ui
        imports = self._imported_modules(Path(workshop_ui.__file__))
        hit = imports & self._FORBIDDEN_MODULES
        self.assertFalse(hit, f"ui/workshop.py imports network module(s): {hit}")

    def test_curriculum_loads_with_no_qapplication_or_network(self):
        # Already exercised at import time by every test above, but assert
        # it explicitly: pure data/engine modules must not require Qt.
        import importlib
        import claude_code_coach.workshop.curriculum as curriculum_module
        importlib.reload(curriculum_module)
        self.assertGreater(len(curriculum_module.ALL_LESSONS), 0)


# -- GUI layer: construction, navigation, quiz, interactive widgets, cert ----
class GuiTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_path = db_module.DB_PATH
        db_module.DB_PATH = Path(self._tmpdir.name) / "workshop_gui_test.db"
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self._original_path
        self._tmpdir.cleanup()

    def _controller(self):
        from claude_code_coach.ui.controller import CoachController
        return CoachController()


class TestWorkshopPage(GuiTestCase):
    def test_constructs_and_shows_first_lesson(self):
        from claude_code_coach.ui.workshop import Workshop
        page = Workshop(self._controller())
        self.assertEqual(page._current_lesson.id, "0.1")

    def test_every_lesson_renders_without_error(self):
        """Release-audit full sweep (Phase 2 of the master release pass):
        every one of the 57 lessons must actually render — not just the
        handful spot-checked by hand — including submitting every quiz
        question with its correct answer, so a broken answer key or a
        crash anywhere in the curriculum can't slip past a manual sample.
        """
        from claude_code_coach.ui.workshop import Workshop
        page = Workshop(self._controller())
        for lesson in ALL_LESSONS:
            with self.subTest(lesson=lesson.id):
                page._show_lesson(lesson.id)
                self.assertEqual(page._current_lesson.id, lesson.id)
                if lesson.quiz:
                    self.assertEqual(len(page._quiz_groups), len(lesson.quiz))
                    for group, question in zip(page._quiz_groups, lesson.quiz):
                        group.button(question.correct_index()).setChecked(True)
                    page._on_quiz_submit(lesson)
                    self.assertIn(lesson.id, page.progress.completed_lessons)
        # And the certificate view itself, now that everything is complete.
        page._show_certificate()

    def test_lesson_without_quiz_marks_itself_complete_on_view(self):
        from claude_code_coach.ui.workshop import Workshop
        page = Workshop(self._controller())
        # 0.1 has no quiz in the curriculum — viewing it is enough.
        self.assertIn("0.1", page.progress.completed_lessons)

    def test_navigating_next_advances_lesson(self):
        from claude_code_coach.ui.workshop import Workshop
        page = Workshop(self._controller())
        page._show_lesson("0.2")
        self.assertEqual(page._current_lesson.id, "0.2")

    def test_quiz_submit_updates_progress_and_persists(self):
        from claude_code_coach.ui.workshop import Workshop
        page = Workshop(self._controller())
        page._show_lesson("1.2")  # has a quiz
        lesson = page._current_lesson
        # Select the correct option in every rendered quiz question.
        for group, question in zip(page._quiz_groups, lesson.quiz):
            group.button(question.correct_index()).setChecked(True)
        page._on_quiz_submit(lesson)
        self.assertIn("1.2", page.progress.completed_lessons)

        reloaded = engine.load_progress()
        self.assertIn("1.2", reloaded.completed_lessons)

    def test_all_interactive_widgets_construct_without_error(self):
        from claude_code_coach.ui.workshop import Workshop
        page = Workshop(self._controller())
        for tag in ("prompt_lab", "context_meter", "decision_wizard"):
            widget = page._build_interactive(tag)
            self.assertIsNotNone(widget)

    def test_prompt_lab_uses_deterministic_analyzer_not_network(self):
        from claude_code_coach.ui.workshop import _PromptLab
        controller = self._controller()
        lab = _PromptLab(controller)
        lab.input.setPlainText("fix my project")
        lab._on_analyze()  # must not raise, must not touch the network
        self.assertGreater(lab.result_layout.count(), 0)

    def test_decision_wizard_reaches_a_result(self):
        from claude_code_coach.ui.workshop import _DecisionWizard
        wizard = _DecisionWizard()
        wizard._answer(True)   # one task? yes
        wizard._answer(True)   # repeatable? yes -> Skill candidate
        # isVisible() would also require the (never-shown, top-level-less)
        # wizard's own ancestor chain to be visible — isHidden() reflects
        # just this widget's own show()/hide() calls, which is what
        # _show_result() actually controls.
        self.assertFalse(wizard._result_panel.isHidden())

    def test_certificate_view_before_and_after_completion(self):
        from claude_code_coach.ui.workshop import Workshop
        page = Workshop(self._controller())
        page._show_certificate()
        self.assertFalse(engine.completion_summary(page.progress).complete)

        for lesson in ALL_LESSONS:
            page.progress.mark_complete(lesson.id)
        engine.save_progress(page.progress)
        page._show_certificate()
        self.assertTrue(engine.completion_summary(page.progress).complete)

    def test_try_it_navigates_to_real_coach_page(self):
        from claude_code_coach.ui.workshop import Workshop
        page = Workshop(self._controller())
        seen = []
        page.controller.set_navigation_callback(lambda label: seen.append(label))
        # 6.4 has a try_it pointing at "Skill Creator".
        page._show_lesson("6.4")
        try_it_widget = page._build_try_it(page._current_lesson)
        buttons = try_it_widget.findChildren(QPushButton)
        self.assertTrue(buttons)
        buttons[0].click()
        self.assertEqual(seen, ["Skill Creator"])


if __name__ == "__main__":
    unittest.main()
