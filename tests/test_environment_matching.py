import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.analyzer import analyze_prompt
from claude_code_coach.integration.environment_matching import (
    build_environment_feedback,
    match_agents,
    match_claude_md,
    match_skills,
)
from claude_code_coach.providers.models import AgentInfo, ClaudeMdInfo, SkillInfo, Source


def _skill(name="security-review", description="Review API endpoints for authentication, "
           "authorization, validation and logging issues."):
    return SkillInfo(name=name, path=f"/fake/{name}/SKILL.md", description=description,
                      source=Source.PROJECT, modified="2026-01-01T00:00:00")


def _agent(name="security-auditor", description="Investigates security-sensitive changes "
           "across the codebase and traces suspicious commits."):
    return AgentInfo(name=name, path=f"/fake/agents/{name}.md", description=description,
                      source=Source.PROJECT, modified="2026-01-01T00:00:00")


def _claude_md(preview="Every API change must include tests and migrations must be reviewed."):
    return ClaudeMdInfo(path="/fake/CLAUDE.md", scope=Source.PROJECT, size_bytes=100,
                         modified="2026-01-01T00:00:00", preview=preview)


class TestSkillMatching(unittest.TestCase):
    def test_existing_skill_match_on_relevant_prompt(self):
        match = match_skills(
            "Review this API endpoint for authentication, authorization, validation and logging.",
            [_skill()],
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.name, "security-review")
        self.assertIn(match.confidence, ("high", "medium"))

    def test_no_match_on_unrelated_prompt(self):
        match = match_skills("Fix the typo in LoginButton.tsx.", [_skill()])
        self.assertIsNone(match)

    def test_no_skills_available_returns_none(self):
        match = match_skills("Review this API for security issues.", [])
        self.assertIsNone(match)


class TestAgentMatching(unittest.TestCase):
    def test_existing_agent_match(self):
        match = match_agents(
            "Investigate security-sensitive changes across the codebase and trace suspicious commits.",
            [_agent()],
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.name, "security-auditor")

    def test_no_match_on_unrelated_prompt(self):
        match = match_agents("Bump the version number in package.json.", [_agent()])
        self.assertIsNone(match)


class TestClaudeMdMatching(unittest.TestCase):
    def test_duplicate_instruction_detected(self):
        match = match_claude_md(
            "Make sure you add tests for every API change before merging this in.",
            [_claude_md()],
        )
        self.assertIsNotNone(match)

    def test_short_clarification_not_flagged(self):
        # Spec section 9: don't aggressively flag normal short clarification.
        match = match_claude_md("Add tests too.", [_claude_md()])
        self.assertIsNone(match)

    def test_unrelated_prompt_not_flagged(self):
        match = match_claude_md(
            "Explain how the retry logic works in the payments client.",
            [_claude_md()],
        )
        self.assertIsNone(match)


class TestEnvironmentFeedbackTriState(unittest.TestCase):
    """Spec sections 10/11: existing / candidate / none must never collapse."""

    def test_existing_skill_state(self):
        prompt = "Review this API endpoint for authentication, authorization, validation and logging."
        analysis = analyze_prompt(prompt)
        fb = build_environment_feedback(prompt, analysis, [_skill()], [], [])
        self.assertEqual(fb.skill_state, "existing")
        self.assertIsNotNone(fb.skill_match)

    def test_skill_candidate_state_when_no_resource_matches(self):
        prompt = (
            "For every PR, inspect changed files, check authentication, authorization, "
            "validation, tests and logging, then produce the same checklist."
        )
        analysis = analyze_prompt(prompt)
        self.assertTrue(any(o.kind == "skill" for o in analysis.opportunities))
        fb = build_environment_feedback(prompt, analysis, [], [], [])
        self.assertEqual(fb.skill_state, "candidate")
        self.assertIsNone(fb.skill_match)

    def test_no_skill_signal_state(self):
        prompt = "Fix typo in LoginButton."
        analysis = analyze_prompt(prompt)
        fb = build_environment_feedback(prompt, analysis, [], [], [])
        self.assertEqual(fb.skill_state, "none")

    def test_existing_agent_state(self):
        prompt = "Investigate security-sensitive changes across the codebase and trace suspicious commits."
        analysis = analyze_prompt(prompt)
        fb = build_environment_feedback(prompt, analysis, [], [_agent()], [])
        self.assertEqual(fb.agent_state, "existing")

    def test_agent_candidate_state(self):
        prompt = (
            "Investigate why memory usage grows over time. Trace the background workers, "
            "compare worker lifecycle behavior, inspect relevant logs and identify the leak."
        )
        analysis = analyze_prompt(prompt)
        self.assertTrue(any(o.kind == "agent" for o in analysis.opportunities))
        fb = build_environment_feedback(prompt, analysis, [], [], [])
        self.assertEqual(fb.agent_state, "candidate")

    def test_no_agent_signal_state(self):
        prompt = "Fix typo in LoginButton."
        analysis = analyze_prompt(prompt)
        fb = build_environment_feedback(prompt, analysis, [], [], [])
        self.assertEqual(fb.agent_state, "none")

    def test_existing_beats_candidate_when_both_conditions_true(self):
        # An actual detected resource must take priority over the inferred signal.
        prompt = (
            "For every PR, review authentication, authorization, validation, tests and "
            "logging, then produce the same checklist."
        )
        analysis = analyze_prompt(prompt)
        fb = build_environment_feedback(prompt, analysis, [_skill()], [], [])
        self.assertEqual(fb.skill_state, "existing")


if __name__ == "__main__":
    unittest.main()
