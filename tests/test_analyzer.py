import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.analyzer import analyze_prompt
from claude_code_coach.analyzer.task_classifier import TaskType, classify


class TestTaskClassifier(unittest.TestCase):
    def test_information_question(self):
        cls = classify("What's the function that handles login?")
        self.assertEqual(cls.primary, TaskType.INFORMATION)
        self.assertTrue(cls.informational)

    def test_explanation(self):
        cls = classify("Explain how the authentication middleware works.")
        self.assertEqual(cls.primary, TaskType.EXPLANATION)

    def test_implementation(self):
        cls = classify("Implement authentication.")
        self.assertEqual(cls.primary, TaskType.IMPLEMENTATION)

    def test_debugging(self):
        cls = classify("Fix the login timeout in src/auth/login.ts. It crashes.")
        self.assertEqual(cls.primary, TaskType.DEBUGGING)

    def test_security_review(self):
        cls = classify("Review src/api/ for SQL injection vulnerabilities.")
        self.assertEqual(cls.primary, TaskType.SECURITY_REVIEW)

    def test_repetitive_workflow(self):
        cls = classify(
            "For every PR, inspect changed files, check authentication, "
            "authorization, validation, tests and logging, then produce the "
            "same checklist."
        )
        self.assertEqual(cls.primary, TaskType.REPETITIVE_WORKFLOW)

    def test_fix_typo_is_not_debugging_or_investigation(self):
        cls = classify("Fix typo in LoginButton.")
        self.assertNotIn(cls.primary, (TaskType.INVESTIGATION,))


class TestPromptAnalyzer(unittest.TestCase):
    def test_empty_prompt(self):
        result = analyze_prompt("")
        self.assertEqual(result.score, 0)
        self.assertEqual(result.rating, "POOR")

    def test_whitespace_only_prompt(self):
        result = analyze_prompt("    \n\t  ")
        self.assertEqual(result.score, 0)
        self.assertEqual(result.rating, "POOR")

    def test_vague_fix_my_project(self):
        result = analyze_prompt("Fix my project.")
        self.assertEqual(result.rating, "POOR")
        self.assertTrue(15 <= result.score <= 30, result.score)
        self.assertFalse(
            any("clear" in g.lower() and "goal" in g.lower() for g in result.good),
            "Vague prompt must not be credited with a clear goal.",
        )

    def test_information_request_not_penalized_for_missing_done(self):
        result = analyze_prompt("Find where JWT tokens are validated.")
        self.assertEqual(result.dimension_status("done"), "na")
        self.assertIn(result.rating, ("GOOD", "EXCELLENT"))

    def test_explanation_not_penalized_for_missing_constraints(self):
        result = analyze_prompt("Explain how the authentication middleware works.")
        self.assertEqual(result.dimension_status("constraints"), "na")

    def test_excellent_debugging_prompt(self):
        result = analyze_prompt(
            "Investigate why the checkout API returns HTTP 500 for valid orders. "
            "Locate the route and tests, reproduce if possible, fix the root "
            "cause and add a regression test."
        )
        self.assertIn(result.rating, ("GOOD", "EXCELLENT"))

    def test_overly_broad_prompt_is_poor(self):
        result = analyze_prompt("Read the entire repository and fix everything you find.")
        self.assertEqual(result.rating, "POOR")

    def test_search_first_warning_present(self):
        result = analyze_prompt("Open every file in the repository before deciding where the bug is.")
        kinds = {o.kind for o in result.opportunities}
        self.assertIn("search_first", kinds)

    def test_skill_candidate_signal(self):
        result = analyze_prompt(
            "For every PR, inspect changed files, check security-sensitive "
            "changes, review authentication, validation, tests and logging, "
            "then produce the same checklist."
        )
        kinds = {o.kind for o in result.opportunities}
        self.assertIn("skill", kinds)

    def test_agent_candidate_signal(self):
        result = analyze_prompt(
            "Investigate why memory usage grows over time. Trace the "
            "background workers, compare worker lifecycle behavior, inspect "
            "relevant logs and identify the likely leak."
        )
        kinds = {o.kind for o in result.opportunities}
        self.assertIn("agent", kinds)

    def test_fix_typo_has_no_agent_signal(self):
        result = analyze_prompt("Fix typo in LoginButton.")
        kinds = {o.kind for o in result.opportunities}
        self.assertNotIn("agent", kinds)

    def test_claude_md_candidate_signal(self):
        result = analyze_prompt(
            "Every API change must include tests and database migrations "
            "must be reviewed before execution."
        )
        kinds = {o.kind for o in result.opportunities}
        self.assertIn("claude_md", kinds)

    def test_context_note_does_not_lower_prompt_quality(self):
        result = analyze_prompt(
            "We've discussed authentication, payments, database migrations "
            "and deployment for hours. Now fix the typo in "
            "`src/components/LoginButton.tsx`."
        )
        self.assertIn(result.rating, ("GOOD", "EXCELLENT"))
        kinds = {o.kind for o in result.opportunities}
        self.assertIn("context", kinds)

    def test_unicode_and_emoji_do_not_crash(self):
        result = analyze_prompt("修复登录问题 🚀 in `src/auth/login.ts`. Done when tests pass.")
        self.assertIsInstance(result.score, int)

    def test_quotes_and_backticks_do_not_crash(self):
        result = analyze_prompt('Fix the "login" bug in `src/auth/login.ts`. Done when tests pass.')
        self.assertIsInstance(result.score, int)

    def test_very_long_prompt_does_not_crash(self):
        result = analyze_prompt("Investigate the bug. " * 500)
        self.assertIsInstance(result.score, int)
        self.assertTrue(0 <= result.score <= 100)

    def test_multiline_prompt(self):
        result = analyze_prompt(
            "Find where the login request is handled.\n"
            "Only inspect src/auth/.\n"
            "Identify the root cause before modifying files.\n"
            "Done when the authentication tests pass.\n"
            "Return only root cause, changed files and test result."
        )
        self.assertIn(result.rating, ("GOOD", "EXCELLENT"))


if __name__ == "__main__":
    unittest.main()
