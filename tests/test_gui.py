"""GUI construction tests.

Runs with the Qt "offscreen" platform so it works in CI / headless
environments. The critical regression this guards against (spec section
33): every QWidget subclass must call super().__init__() BEFORE creating
any child Qt object (QTimer, QLabel, layouts, ...). Constructing every page
here would raise if that order were ever wrong.
"""

import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QMessageBox

from claude_code_coach.database import db as db_module

_app = QApplication.instance() or QApplication(sys.argv)


def _wait_for_scan(controller, timeout_s: float = 5.0) -> None:
    """save_skill_file()/save_agent_file() kick off an async environment
    re-scan on a background QThread. Tests that immediately clean up a
    temp project directory afterward must wait for it first, or Windows
    can raise PermissionError deleting a file the scan thread still has open.
    """
    import time
    deadline = time.monotonic() + timeout_s
    while controller.is_scanning() and time.monotonic() < deadline:
        _app.processEvents()


@contextmanager
def no_blocking_dialogs():
    """QMessageBox.exec()/information()/warning()/critical() are modal and
    would hang a headless test run waiting for a click that never comes —
    this stands in for "the user clicked OK" without actually blocking.
    """
    with patch.object(QMessageBox, "exec", return_value=QMessageBox.Ok), \
         patch.object(QMessageBox, "information", return_value=QMessageBox.Ok), \
         patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok), \
         patch.object(QMessageBox, "critical", return_value=QMessageBox.Ok):
        yield


class GuiTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_path = db_module.DB_PATH
        db_module.DB_PATH = Path(self._tmpdir.name) / "gui_test.db"
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self._original_path
        self._tmpdir.cleanup()


class TestMainWindow(GuiTestCase):
    def test_main_window_constructs_and_navigates(self):
        from claude_code_coach.ui.main_window import MainWindow

        window = MainWindow()
        self.assertEqual(window.stack.count(), len(window.pages))
        for i in range(window.stack.count()):
            window._navigate(i)
            self.assertEqual(window.stack.currentIndex(), i)
        window.close()


class TestIndividualPages(GuiTestCase):
    def _controller(self):
        from claude_code_coach.ui.controller import CoachController
        return CoachController()

    def test_dashboard(self):
        from claude_code_coach.ui.dashboard import Dashboard
        page = Dashboard(self._controller())
        page.refresh()

    def test_inspector_live_coach(self):
        from claude_code_coach.ui.inspector import Inspector
        page = Inspector(self._controller())
        page.editor.setPlainText("Fix my project.")
        page._live_analyze()
        self.assertIn(page.score_pill.rating_label.text(), ("POOR", "NEEDS IMPROVEMENT"))

    def test_inspector_analyze_saves_to_history(self):
        controller = self._controller()
        from claude_code_coach.ui.inspector import Inspector
        page = Inspector(controller)
        page.editor.setPlainText(
            "Fix the login timeout in src/auth/login.ts. Done when tests pass."
        )
        page._on_analyze()
        self.assertEqual(controller.count(), 1)

    def test_history_empty_and_populated(self):
        from claude_code_coach.ui.history import History
        controller = self._controller()
        page = History(controller)
        page.refresh()

        result = controller.analyze("Fix the bug in src/x.py. Done when tests pass.")
        controller.save(result)
        page.refresh()
        self.assertGreaterEqual(page.list.count(), 1)

    def test_habits(self):
        from claude_code_coach.ui.habits import Habits
        page = Habits(self._controller())
        page.refresh()

    def test_skills(self):
        from claude_code_coach.ui.skills import Skills
        page = Skills(self._controller())
        page.refresh()

    def test_agents(self):
        from claude_code_coach.ui.agents import Agents
        page = Agents(self._controller())
        page.refresh()

    def test_context(self):
        from claude_code_coach.ui.context import Context
        page = Context(self._controller())
        page.refresh()

    def test_environment_page_empty(self):
        from claude_code_coach.ui.environment import Environment
        page = Environment(self._controller())
        page.refresh()

    def test_environment_page_after_sync_scan(self):
        import tempfile
        import textwrap
        from claude_code_coach.providers import ClaudeCodeEnvironmentProvider
        from claude_code_coach.ui.environment import Environment

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            fake_home = Path(tmp) / "home"
            skills_dir = root / ".claude" / "skills" / "demo-skill"
            skills_dir.mkdir(parents=True)
            (skills_dir / "SKILL.md").write_text(
                "---\nname: demo-skill\ndescription: a demo\n---\nBody\n", encoding="utf-8"
            )
            fake_home.mkdir()

            controller = self._controller()
            controller.environment = ClaudeCodeEnvironmentProvider(
                project_root=root, user_home=fake_home
            )
            controller.scan_environment_sync()

            page = Environment(controller)
            page.refresh()
            self.assertEqual(controller.environment_snapshot.counts["skills"], 1)

    def test_runtime_page_empty(self):
        from claude_code_coach.ui.runtime import Runtime
        page = Runtime(self._controller())
        page.refresh()

    def test_runtime_page_after_fixture_session(self):
        from claude_code_coach.runtime.event_source import HookFileEventSource
        from claude_code_coach.runtime.models import RuntimeEvent, RuntimeEventType as T
        from claude_code_coach.ui.runtime import Runtime

        controller = self._controller()
        db_module.insert_runtime_event(RuntimeEvent(
            id=None, received_at=__import__("datetime").datetime.now().isoformat(timespec="seconds"),
            session_id="fixture-1", event_type=T.USER_PROMPT_SUBMIT,
            metadata={"word_count": 4, "tokens": [], "task_type": "implementation",
                      "scope_status": "clear", "breadth_level": 0, "vague_goal": False},
        ))

        page = Runtime(controller)
        page.refresh()
        self.assertIn("LIVE", page.state_label.text())

    # -- V5 pages ---------------------------------------------------------------
    def test_approach_advisor_page(self):
        from claude_code_coach.ui.approach_advisor import ApproachAdvisor
        page = ApproachAdvisor(self._controller())
        page.input.setPlainText("Investigate why the test suite is slow across backend, "
                                 "database and frontend.")
        page._on_get_approach()
        self.assertIn("Independent work", page.output.toPlainText())

    def test_approach_advisor_empty_input(self):
        from claude_code_coach.ui.approach_advisor import ApproachAdvisor
        page = ApproachAdvisor(self._controller())
        page._on_get_approach()
        self.assertIn("Describe a task", page.output.toPlainText())

    def test_workshop_page_toggle_persists(self):
        controller = self._controller()
        from claude_code_coach.ui.workshop import Workshop
        page = Workshop(controller)
        self.assertFalse(controller.workshop_mode)
        page.toggle.setChecked(True)
        self.assertTrue(controller.workshop_mode)

    def test_integrations_page_empty(self):
        from claude_code_coach.ui.mcp_page import Integrations
        page = Integrations(self._controller())
        page.refresh()

    def test_skill_creator_construction_empty(self):
        from claude_code_coach.ui.skill_creator import SkillCreator
        page = SkillCreator(self._controller())
        page.refresh()

    def test_skill_creator_validation_error_shown(self):
        from claude_code_coach.ui.skill_creator import SkillCreator
        page = SkillCreator(self._controller())
        page.name_edit.setText("Not Valid!")
        page._on_generate_preview()
        self.assertIn("kebab-case", page.message_label.text())
        self.assertEqual(page.preview_text.toPlainText(), "")

    def test_skill_creator_full_save_flow_with_real_project(self):
        import tempfile
        from claude_code_coach.providers import ClaudeCodeEnvironmentProvider
        from claude_code_coach.ui.skill_creator import SkillCreator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            controller = self._controller()
            controller.environment = ClaudeCodeEnvironmentProvider(
                project_root=root, user_home=Path(tmp) / "home"
            )

            page = SkillCreator(controller)
            page.name_edit.setText("security-review")
            page.fields["purpose"].setPlainText("Review API endpoints for security issues.")
            page.fields["when_to_use"].setPlainText("When reviewing an endpoint.")
            page.fields["workflow"].setPlainText("Check auth, validation, logging.")
            page._on_generate_preview()
            self.assertIn("security-review", page.preview_text.toPlainText())

            with no_blocking_dialogs():
                page._on_save()
            _wait_for_scan(controller)
            saved_path = root / ".claude" / "skills" / "security-review" / "SKILL.md"
            self.assertTrue(saved_path.is_file())

            # Draft is cleared after a successful save.
            self.assertIsNone(controller.load_skill_draft())

    def test_skill_creator_draft_persists_across_page_construction(self):
        controller = self._controller()
        from claude_code_coach.ui.skill_creator import SkillCreator
        page1 = SkillCreator(controller)
        page1.name_edit.setText("my-skill")
        page1.fields["purpose"].setPlainText("Some purpose text.")
        page1._on_generate_preview()  # triggers draft persistence

        page2 = SkillCreator(controller)
        self.assertEqual(page2.name_edit.text(), "my-skill")

    def test_agent_creator_construction_empty(self):
        from claude_code_coach.ui.agent_creator import AgentCreator
        page = AgentCreator(self._controller())
        page.refresh()

    def test_agent_creator_validation_error_shown(self):
        from claude_code_coach.ui.agent_creator import AgentCreator
        page = AgentCreator(self._controller())
        page.name_edit.setText("")
        page._on_generate_preview()
        self.assertIn("required", page.message_label.text())

    def test_agent_creator_full_save_flow_with_real_project(self):
        import tempfile
        from claude_code_coach.providers import ClaudeCodeEnvironmentProvider
        from claude_code_coach.ui.agent_creator import AgentCreator

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            controller = self._controller()
            controller.environment = ClaudeCodeEnvironmentProvider(
                project_root=root, user_home=Path(tmp) / "home"
            )

            page = AgentCreator(controller)
            page.name_edit.setText("test-investigator")
            page.fields["purpose"].setPlainText("Investigate failing tests.")
            page.fields["role"].setPlainText("Test failure investigator")
            page.fields["responsibilities"].setPlainText("Find root cause of failures.")
            page._on_generate_preview()
            with no_blocking_dialogs():
                page._on_save()
            _wait_for_scan(controller)

            saved_path = root / ".claude" / "agents" / "test-investigator.md"
            self.assertTrue(saved_path.is_file())

    def test_dashboard_recommendations_section(self):
        from claude_code_coach.ui.dashboard import Dashboard
        controller = self._controller()
        page = Dashboard(controller)
        page.refresh()  # empty state must not crash

        result = controller.analyze("Fix the bug in src/x.py. Done when tests pass.")
        controller.save(result)
        page.refresh()

    def test_settings(self):
        from claude_code_coach.ui.settings import Settings
        page = Settings(self._controller())
        page.refresh()

    def test_is_scanning_after_async_scan_completes_does_not_raise(self):
        """Regression test for a real bug: once a background environment
        scan (scan_environment_async, e.g. the one app.py kicks off on
        startup) finished, its QThread's underlying C++ object could
        already be deleted (thread.finished -> thread.deleteLater()) while
        controller._scan_thread still pointed at it — so any later
        is_scanning() call (e.g. environment.py's refresh(), reached via
        Prompt Inspector's "Analyze & Save" -> refresh_all()) raised
        `RuntimeError: libshiboken: Internal C++ object (QThread) already
        deleted`. scan_environment_async() must clear _scan_thread once the
        scan finishes, not just quit() it.
        """
        import tempfile
        from claude_code_coach.providers import ClaudeCodeEnvironmentProvider

        controller = self._controller()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            controller.environment = ClaudeCodeEnvironmentProvider(
                project_root=root, user_home=Path(tmp) / "home"
            )

            started = controller.scan_environment_async()
            self.assertTrue(started)
            _wait_for_scan(controller)

            # Must not raise (this is what used to hit "libshiboken:
            # Internal C++ object already deleted").
            self.assertFalse(controller.is_scanning())

    def test_refresh_all_after_analyze_and_save_does_not_raise(self):
        """End-to-end regression test for the exact reported symptom:
        Prompt Inspector's Analyze & Save button calls controller.save()
        then controller.refresh_all(), which reaches the Environment page's
        refresh() -> controller.is_scanning() -- this must not raise even
        when a prior async environment scan (e.g. app.py's startup scan)
        has already completed (see
        test_is_scanning_after_async_scan_completes_does_not_raise).
        """
        import tempfile
        from claude_code_coach.providers import ClaudeCodeEnvironmentProvider
        from claude_code_coach.ui.environment import Environment

        controller = self._controller()
        controller.register(Environment(controller))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            controller.environment = ClaudeCodeEnvironmentProvider(
                project_root=root, user_home=Path(tmp) / "home"
            )

            controller.scan_environment_async()
            _wait_for_scan(controller)

            result = controller.analyze("Fix the login timeout bug in src/auth/login.ts.")
            controller.save(result)
            controller.refresh_all()  # must not raise

    def test_settings_runtime_controls(self):
        from claude_code_coach.ui.settings import Settings
        controller = self._controller()
        page = Settings(controller)

        self.assertFalse(controller.runtime_collect_content())
        page.collect_content_checkbox.setChecked(True)
        self.assertTrue(controller.runtime_collect_content())

        page.retention_combo.setCurrentIndex(0)  # "7 days"
        self.assertEqual(controller.runtime_retention_days(), 7)

    def test_settings_scan_on_startup_toggle_persists(self):
        controller = self._controller()
        from claude_code_coach.ui.settings import Settings
        page = Settings(controller)

        self.assertFalse(controller.scan_on_startup)
        page.scan_startup_checkbox.setChecked(True)
        self.assertTrue(controller.scan_on_startup)

        # A fresh controller reading the same (temp) DB should see it persisted.
        controller2 = self._controller()
        self.assertTrue(controller2.scan_on_startup)

    def test_settings_clear_all_via_controller(self):
        controller = self._controller()
        from claude_code_coach.ui.settings import Settings
        page = Settings(controller)

        result = controller.analyze("Fix the bug in src/x.py. Done when tests pass.")
        controller.save(result)
        self.assertEqual(controller.count(), 1)

        controller.clear_all()
        self.assertEqual(controller.count(), 0)
        page.refresh()
        self.assertIn("0", page.db_info_label.text())


class TestFullAcceptanceFlow(GuiTestCase):
    def test_acceptance_flow(self):
        """Mirrors spec section 34's manual acceptance test."""
        from claude_code_coach.ui.main_window import MainWindow

        window = MainWindow()
        from claude_code_coach.ui.main_window import PAGES
        index = {label: i for i, (label, _cls) in enumerate(PAGES)}

        inspector = window.pages[index["Prompt Inspector"]]
        history = window.pages[index["Prompt History"]]

        window._navigate(index["Prompt Inspector"])
        inspector.editor.setPlainText("Fix my project.")
        inspector._live_analyze()
        self.assertEqual(inspector.score_pill.rating_label.text(), "POOR")

        inspector._on_analyze()

        window._navigate(index["Prompt History"])
        self.assertGreaterEqual(history.list.count(), 1)

        window._navigate(index["Dashboard"])
        self.assertEqual(window.controller.count(), 1)

        # Every V5 page must also construct/refresh cleanly.
        for label in ("Approach Advisor", "Sessions", "Skills", "Skill Creator",
                      "Agents", "Agent Creator", "Integrations", "Environment",
                      "Habits", "Workshop Mode"):
            window._navigate(index[label])

        window._navigate(index["Settings"])
        window.controller.clear_all()
        self.assertEqual(window.controller.count(), 0)

        window.close()


if __name__ == "__main__":
    unittest.main()
