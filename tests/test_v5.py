"""V5 adversarial test suite: prompt suggestions, Approach Advisor, session
coherence/verification, and Skill/Agent Creator safety. Existing V4
benchmarks (prompt/runtime) are untouched and re-verified separately by
tests/run_benchmark.py and tests/run_runtime_benchmark.py.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.analyzer import analyze_prompt
from claude_code_coach.analyzer.prompt_rewriter import PromptCategory, suggest_prompt
from claude_code_coach.creators import (
    AgentDraft,
    SkillDraft,
    agent_path,
    render_agent_md,
    render_skill_md,
    save_agent,
    save_skill,
    skill_path,
    validate_agent_draft,
    validate_skill_draft,
)
from claude_code_coach.integration.approach_advisor import recommend_approach
from claude_code_coach.providers.models import AgentInfo, ClaudeMdInfo, McpServerInfo, SkillInfo, Source
from claude_code_coach.runtime import event_parser, runtime_analyzer
from claude_code_coach.runtime.models import RuntimeEventType


# ============================================================================
# FEATURE 1: Prompt suggestions
# ============================================================================
class TestPromptSuggestionsVague(unittest.TestCase):
    def test_vague_goal_gets_canonical_rewrite(self):
        s = suggest_prompt("Fix my project.")
        self.assertEqual(s.category, PromptCategory.UNDERSPECIFIED)
        self.assertIn("Investigate the issue", s.suggested_text)

    def test_make_it_better_gets_canonical_rewrite(self):
        s = suggest_prompt("Make the app better.")
        self.assertEqual(s.category, PromptCategory.UNDERSPECIFIED)
        self.assertIsNotNone(s.suggested_text)

    def test_empty_prompt(self):
        s = suggest_prompt("")
        self.assertEqual(s.category, PromptCategory.EMPTY)
        self.assertIsNone(s.suggested_text)

    def test_whitespace_only_prompt(self):
        s = suggest_prompt("   \n\t ")
        self.assertEqual(s.category, PromptCategory.EMPTY)


class TestPromptSuggestionsGood(unittest.TestCase):
    def test_already_good_prompt_gets_no_rewrite(self):
        s = suggest_prompt(
            "Investigate why valid users cannot log in after the latest API change. "
            "Focus on the authentication flow and related tests. Don't change the "
            "API response contract. Implement the minimal fix and run the relevant tests."
        )
        self.assertEqual(s.category, PromptCategory.GOOD)
        self.assertIsNone(s.suggested_text)

    def test_good_prompt_missing_done_gets_light_nudge_not_full_rewrite(self):
        s = suggest_prompt("Fix the login issue in auth.py. Valid users cannot log in "
                            "after the latest API change. Don't change the API response format.")
        self.assertEqual(s.category, PromptCategory.GOOD)
        self.assertIsNone(s.suggested_text)
        self.assertIn("done", s.message.lower())


class TestPromptSuggestionsInformational(unittest.TestCase):
    def test_information_question_not_rewritten(self):
        s = suggest_prompt("What's the function that handles login?")
        self.assertEqual(s.category, PromptCategory.INFORMATIONAL)
        self.assertIsNone(s.suggested_text)

    def test_explanation_request_not_rewritten(self):
        s = suggest_prompt("Explain how the authentication middleware works.")
        self.assertEqual(s.category, PromptCategory.INFORMATIONAL)


class TestPromptSuggestionsBroad(unittest.TestCase):
    def test_broad_justified_research_not_penalized(self):
        s = suggest_prompt(
            "Research which HTTP client library across our codebase would be best "
            "to standardize on; compare options and alternatives."
        )
        self.assertIn(s.category, (PromptCategory.BROAD_JUSTIFIED, PromptCategory.GOOD))

    def test_broad_justified_security_audit(self):
        s = suggest_prompt(
            "Search src/ for all uses of localStorage related to authentication. "
            "Summarize risky patterns. Don't modify anything."
        )
        self.assertIn(s.category, (PromptCategory.GOOD, PromptCategory.BROAD_JUSTIFIED))

    def test_broad_inefficient_narrow_task_flagged(self):
        s = suggest_prompt("Read the entire repository and fix everything you find.")
        self.assertIn(s.category, (PromptCategory.UNDERSPECIFIED, PromptCategory.BROAD_INEFFICIENT))


class TestPromptSuggestionsExtraction(unittest.TestCase):
    def test_filename_preserved_in_suggestion(self):
        s = suggest_prompt("Something is wrong with parsing in billing.py, it crashes sometimes.")
        self.assertIn("billing.py", s.extraction.files)

    def test_constraint_preserved(self):
        s = suggest_prompt(
            "Fix the crash in billing.py. Don't change the public API. It crashes on large invoices."
        )
        self.assertTrue(any("don't change" in c.lower() for c in s.extraction.constraints))

    def test_expected_behavior_extracted(self):
        s = suggest_prompt("The export button should download a CSV but instead nothing happens.")
        self.assertTrue(s.extraction.expected_behavior or s.extraction.error_descriptions)

    def test_error_description_extracted(self):
        s = suggest_prompt("Users report the checkout API returns a 500 error after checkout.")
        self.assertTrue(any("500" in e or "error" in e.lower() for e in s.extraction.error_descriptions))

    def test_requested_output_extracted(self):
        s = suggest_prompt("Review src/api/ for issues and return a table of findings with severity.")
        self.assertTrue(s.extraction.requested_outputs)

    def test_function_name_extracted(self):
        s = suggest_prompt("What does parseInvoice() do and where is it called from?")
        self.assertIn("parseInvoice()", s.extraction.functions)

    def test_no_facts_invented_for_vague_prompt(self):
        s = suggest_prompt("Fix my project.")
        self.assertEqual(s.extraction.files, [])
        self.assertEqual(s.extraction.constraints, [])

    def test_independent_areas_extracted(self):
        s = suggest_prompt("Investigate why the test suite is slow across backend, database and frontend.")
        self.assertEqual(set(s.extraction.independent_areas), {"backend", "database", "frontend"})

    def test_sequential_connector_detected(self):
        s = suggest_prompt("First investigate the backend, then once that's done look at the frontend.")
        self.assertTrue(s.extraction.has_sequential_connector)


class TestPromptSuggestionsOverlyPrescriptive(unittest.TestCase):
    def test_long_prescriptive_prompt_flagged(self):
        prompt = (
            "Step 1: open src/auth/login.ts. Step 2: locate the validateToken function. "
            "Don't change the function signature. Don't add new dependencies. Don't touch "
            "any other file. Step 3: add a null check exactly as follows: check token is "
            "not null before calling decode. Step 4: run the tests. Step 5: report back "
            "with the exact diff and nothing else, formatted as a unified diff block."
        )
        s = suggest_prompt(prompt)
        self.assertEqual(s.category, PromptCategory.OVERLY_PRESCRIPTIVE)

    def test_short_prompt_not_flagged_as_prescriptive(self):
        s = suggest_prompt("Fix the bug in auth.py.")
        self.assertNotEqual(s.category, PromptCategory.OVERLY_PRESCRIPTIVE)


class TestPromptSuggestionsUnicode(unittest.TestCase):
    def test_unicode_prompt_does_not_crash(self):
        s = suggest_prompt("修复登录问题 in `src/auth/login.ts`. 🚀 Done when tests pass.")
        self.assertIsInstance(s.category, PromptCategory)

    def test_emoji_only_prompt_does_not_crash(self):
        s = suggest_prompt("🔥🔥🔥")
        self.assertIsInstance(s.category, PromptCategory)


# ============================================================================
# FEATURE 2: Approach Advisor
# ============================================================================
def _skill(name="security-review", desc="Review API endpoints for authentication, "
           "authorization, validation and logging issues."):
    return SkillInfo(name=name, path="/f/SKILL.md", description=desc, source=Source.PROJECT, modified="")


def _agent(name="test-investigator", desc="Investigates failing API tests across the codebase."):
    return AgentInfo(name=name, path="/f/agent.md", description=desc, source=Source.PROJECT, modified="")


def _claude_md(preview="Every API change must include tests and migrations must be reviewed."):
    return ClaudeMdInfo(path="/f/CLAUDE.md", scope=Source.PROJECT, size_bytes=10, modified="", preview=preview)


def _mcp(name="database"):
    return McpServerInfo(name=name, server_type="stdio", source=Source.PROJECT, config_path="/f/.mcp.json")


class _FakeSnapshot:
    def __init__(self, skills=None, agents=None, claude_md=None, mcp_servers=None):
        self.skills = skills or []
        self.agents = agents or []
        self.claude_md = claude_md or []
        self.mcp_servers = mcp_servers or []


class TestApproachAdvisor(unittest.TestCase):
    def test_existing_skill_recommended(self):
        prompt = "Investigate why our API tests are failing on authentication and validation."
        analysis = analyze_prompt(prompt)
        report = recommend_approach(prompt, analysis, _FakeSnapshot(skills=[_skill()]))
        self.assertTrue(any(r.kind == "skill_existing" for r in report.recommendations))

    def test_inferred_skill_candidate_when_no_environment(self):
        prompt = (
            "For every PR, inspect changed files, check authentication, authorization, "
            "validation, tests and logging, then produce the same checklist."
        )
        analysis = analyze_prompt(prompt)
        report = recommend_approach(prompt, analysis, None)
        self.assertTrue(any(r.kind == "skill_candidate" for r in report.recommendations))

    def test_existing_agent_recommended(self):
        prompt = "Investigate failing API tests across the codebase and find the root cause."
        analysis = analyze_prompt(prompt)
        report = recommend_approach(prompt, analysis, _FakeSnapshot(agents=[_agent()]))
        self.assertTrue(any(r.kind == "agent_existing" for r in report.recommendations))

    def test_inferred_agent_candidate(self):
        prompt = ("Investigate why memory usage grows over time. Trace the background "
                  "workers, compare worker lifecycle behavior, inspect relevant logs "
                  "and identify the likely leak.")
        analysis = analyze_prompt(prompt)
        report = recommend_approach(prompt, analysis, None)
        self.assertTrue(any(r.kind == "agent_candidate" for r in report.recommendations))

    def test_relevant_mcp_surfaced(self):
        prompt = "Query the database MCP server to check current row counts."
        analysis = analyze_prompt(prompt)
        report = recommend_approach(prompt, analysis, _FakeSnapshot(mcp_servers=[_mcp("database")]))
        self.assertTrue(any(r.kind == "mcp_relevant" for r in report.recommendations))

    def test_irrelevant_mcp_not_surfaced(self):
        prompt = "Fix the typo in LoginButton.tsx."
        analysis = analyze_prompt(prompt)
        report = recommend_approach(prompt, analysis, _FakeSnapshot(mcp_servers=[_mcp("database")]))
        self.assertFalse(any(r.kind == "mcp_relevant" for r in report.recommendations))

    def test_claude_md_repetition_surfaced(self):
        prompt = "Make sure you add tests for every API change and get migrations reviewed."
        analysis = analyze_prompt(prompt)
        report = recommend_approach(prompt, analysis, _FakeSnapshot(claude_md=[_claude_md()]))
        self.assertTrue(any(r.kind == "claude_md" for r in report.recommendations))

    def test_no_environment_falls_back_to_normal_session(self):
        prompt = "Fix typo in LoginButton."
        analysis = analyze_prompt(prompt)
        report = recommend_approach(prompt, analysis, None)
        kinds = {r.kind for r in report.recommendations}
        self.assertTrue(kinds == {"normal_session"} or not kinds - {"normal_session"})

    def test_conflicting_signals_both_present_existing_wins_over_candidate(self):
        # Same prompt would independently look like a skill candidate AND
        # match a detected skill — existing must win, candidate must not
        # also appear for the same resource type.
        prompt = (
            "For every PR, review authentication, authorization, validation, tests and "
            "logging, then produce the same checklist."
        )
        analysis = analyze_prompt(prompt)
        report = recommend_approach(prompt, analysis, _FakeSnapshot(skills=[_skill(
            desc="Review authentication, authorization, validation, tests and logging "
                 "for every PR."
        )]))
        kinds = [r.kind for r in report.recommendations]
        self.assertIn("skill_existing", kinds)
        self.assertNotIn("skill_candidate", kinds)

    def test_parallel_work_and_skill_can_coexist(self):
        prompt = ("Investigate why the test suite is slow across backend, database and "
                  "frontend. Review authentication, validation, tests and logging too.")
        analysis = analyze_prompt(prompt)
        report = recommend_approach(prompt, analysis, None)
        kinds = {r.kind for r in report.recommendations}
        self.assertIn("parallel_work", kinds)

    def test_report_top_respects_level_ordering(self):
        # A high-confidence skill match (near-total token overlap) must
        # outrank a lower-confidence one when both are present.
        strong_skill = _skill(name="api-test-triage",
                               desc="Investigate why api tests are failing across the codebase.")
        weak_agent = _agent()  # only medium-confidence overlap with this prompt
        prompt = "Investigate why our API tests are failing."
        analysis = analyze_prompt(prompt)
        report = recommend_approach(prompt, analysis, _FakeSnapshot(skills=[strong_skill], agents=[weak_agent]))
        top = report.top(1)
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0].kind, "skill_existing")
        self.assertEqual(top[0].level, "high")


# ============================================================================
# FEATURE 6/8/9: Session coherence, context health, verification
# ============================================================================
def _events(*raw):
    return [event_parser.parse_hook_payload({**r, "session_id": "s"}) for r in raw]


class TestSessionCoherence(unittest.TestCase):
    def test_healthy_long_session_no_warning(self):
        # Shares literal tokens (including the exact file path) across every
        # prompt — a realistic "one continuous task" session. Session
        # coherence intentionally uses the same path-sensitive tokenizer as
        # prompt-history clustering; see Known limitations for the tradeoff
        # this implies when wording/path depth varies within one real task.
        events = _events(
            {"hook_event_name": "UserPromptSubmit",
             "prompt": "Understand the auth flow in src/auth/login.ts."},
            {"hook_event_name": "UserPromptSubmit",
             "prompt": "Now investigate the auth flow bug in src/auth/login.ts."},
            {"hook_event_name": "UserPromptSubmit",
             "prompt": "Implement the auth flow fix in src/auth/login.ts."},
            {"hook_event_name": "UserPromptSubmit",
             "prompt": "Run the auth flow tests for src/auth/login.ts to verify."},
        )
        health, signals = runtime_analyzer.session_coherence(events)
        self.assertGreaterEqual(health, 70)
        self.assertFalse(any(s.kind == "context_noisy" for s in signals))

    def test_unrelated_task_switch_flagged(self):
        events = _events(
            {"hook_event_name": "UserPromptSubmit", "prompt": "Fix the login timeout in src/auth/login.ts."},
            {"hook_event_name": "UserPromptSubmit", "prompt": "What color scheme does the frontend use?"},
            {"hook_event_name": "UserPromptSubmit", "prompt": "Bump the version number in package.json."},
        )
        health, signals = runtime_analyzer.session_coherence(events)
        self.assertLess(health, 100)
        self.assertTrue(any(s.kind == "context_noisy" for s in signals))

    def test_continuous_investigation_not_flagged(self):
        events = _events(
            {"hook_event_name": "UserPromptSubmit", "prompt": "Investigate why memory usage grows in src/workers/."},
            {"hook_event_name": "UserPromptSubmit", "prompt": "Investigate memory usage further in src/workers/pool.py."},
        )
        health, signals = runtime_analyzer.session_coherence(events)
        self.assertFalse(any(s.kind == "context_noisy" for s in signals))

    def test_compaction_lowers_health(self):
        events = _events(
            {"hook_event_name": "UserPromptSubmit", "prompt": "Continue the refactor."},
            {"hook_event_name": "PreCompact", "trigger": "auto"},
        )
        health, _signals = runtime_analyzer.session_coherence(events)
        self.assertLess(health, 100)

    def test_no_prompts_returns_full_health(self):
        events = _events({"hook_event_name": "SessionStart", "cwd": "/proj"})
        health, signals = runtime_analyzer.session_coherence(events)
        self.assertEqual(health, 100)
        self.assertEqual(signals, [])

    def test_length_alone_does_not_lower_health(self):
        raw = [{"hook_event_name": "UserPromptSubmit",
                "prompt": f"Continue fixing the auth flow in src/auth/login.ts, step {i}."}
               for i in range(10)]
        events = _events(*raw)
        health, signals = runtime_analyzer.session_coherence(events)
        self.assertGreaterEqual(health, 70)


class TestVerificationSignal(unittest.TestCase):
    def test_test_command_after_edit_is_verified(self):
        events = _events(
            {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "src/a.py"}},
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "pytest tests/"}},
        )
        signals = runtime_analyzer.verification_signal(events)
        self.assertTrue(any(s.kind == "verification_done" for s in signals))

    def test_edit_with_no_followup_is_unverified(self):
        events = _events(
            {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "src/a.py"}},
        )
        signals = runtime_analyzer.verification_signal(events)
        self.assertTrue(any(s.kind == "verification_missing" for s in signals))
        self.assertIn("no verification activity was observed", signals[0].message.lower())
        self.assertNotIn("didn't test", signals[0].message.lower())

    def test_unrelated_command_after_edit_is_unverified(self):
        events = _events(
            {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "src/a.py"}},
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls -la"}},
        )
        signals = runtime_analyzer.verification_signal(events)
        self.assertTrue(any(s.kind == "verification_missing" for s in signals))

    def test_investigation_only_task_no_edits_no_signal(self):
        events = _events(
            {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "src/a.py"}},
            {"hook_event_name": "PreToolUse", "tool_name": "Grep", "tool_input": {"pattern": "foo"}},
        )
        signals = runtime_analyzer.verification_signal(events)
        self.assertEqual(signals, [])

    def test_documentation_task_no_edits_no_signal(self):
        events = _events(
            {"hook_event_name": "UserPromptSubmit", "prompt": "Explain how the retry logic works."},
        )
        signals = runtime_analyzer.verification_signal(events)
        self.assertEqual(signals, [])

    def test_subagent_after_edit_counts_as_verification(self):
        events = _events(
            {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "src/a.py"}},
            {"hook_event_name": "SubagentStop", "agent_type": "general-purpose", "agent_id": "a1"},
        )
        signals = runtime_analyzer.verification_signal(events)
        self.assertTrue(any(s.kind == "verification_done" for s in signals))


# ============================================================================
# FEATURE 3/4/19: Skill/Agent Creator safety
# ============================================================================
class TestCreatorSafetyBase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()


class TestSkillCreatorSafety(TestCreatorSafetyBase):
    def _draft(self, name="security-review"):
        return SkillDraft(name=name, purpose="Review API endpoints.",
                           when_to_use="When reviewing an endpoint.",
                           workflow="Check auth, validation, logging.")

    def test_valid_draft_passes(self):
        v = validate_skill_draft(self._draft(), self.root)
        self.assertTrue(v.ok)

    def test_malformed_name_rejected(self):
        v = validate_skill_draft(self._draft(name="Not A Valid Name!"), self.root)
        self.assertFalse(v.ok)

    def test_empty_name_rejected(self):
        v = validate_skill_draft(self._draft(name=""), self.root)
        self.assertFalse(v.ok)

    def test_empty_purpose_rejected(self):
        d = self._draft()
        d.purpose = ""
        v = validate_skill_draft(d, self.root)
        self.assertFalse(v.ok)

    def test_empty_workflow_rejected(self):
        d = self._draft()
        d.workflow = ""
        v = validate_skill_draft(d, self.root)
        self.assertFalse(v.ok)

    def test_duplicate_skill_warns_but_does_not_error(self):
        save_skill(self.root, self._draft())
        v = validate_skill_draft(self._draft(), self.root)
        self.assertTrue(v.ok)
        self.assertTrue(v.already_exists)
        self.assertTrue(v.warnings)

    def test_save_without_overwrite_on_duplicate_raises(self):
        save_skill(self.root, self._draft())
        with self.assertRaises(FileExistsError):
            save_skill(self.root, self._draft())

    def test_save_with_overwrite_succeeds(self):
        save_skill(self.root, self._draft())
        result = save_skill(self.root, self._draft(), overwrite=True)
        self.assertTrue(Path(result["path"]).exists())

    def test_preview_without_save_writes_nothing(self):
        draft = self._draft()
        render_skill_md(draft)  # preview only
        self.assertFalse(skill_path(self.root, draft.name).exists())

    def test_explicit_save_writes_file(self):
        draft = self._draft()
        result = save_skill(self.root, draft)
        self.assertTrue(Path(result["path"]).is_file())

    def test_secret_redacted_in_rendered_output(self):
        draft = self._draft()
        draft.constraints = "Uses API_KEY=super-secret-value for auth in tests."
        rendered = render_skill_md(draft)
        self.assertNotIn("super-secret-value", rendered)

    def test_save_invalid_draft_raises_value_error(self):
        with self.assertRaises(ValueError):
            save_skill(self.root, self._draft(name=""))

    def test_atomic_write_leaves_no_temp_file_on_success(self):
        save_skill(self.root, self._draft())
        leftovers = list((self.root / ".claude" / "skills" / "security-review").glob(".coach_write_*"))
        self.assertEqual(leftovers, [])

    def test_existing_skill_names_reflects_saved_skill(self):
        from claude_code_coach.creators import existing_skill_names
        save_skill(self.root, self._draft())
        self.assertIn("security-review", existing_skill_names(self.root))


class TestAgentCreatorSafety(TestCreatorSafetyBase):
    def _draft(self, name="test-investigator"):
        return AgentDraft(name=name, purpose="Investigate failing tests.",
                           role="Test failure investigator",
                           responsibilities="Find root cause of test failures.")

    def test_valid_draft_passes(self):
        v = validate_agent_draft(self._draft(), self.root)
        self.assertTrue(v.ok)

    def test_malformed_name_rejected(self):
        v = validate_agent_draft(self._draft(name="Bad Name"), self.root)
        self.assertFalse(v.ok)

    def test_empty_role_rejected(self):
        d = self._draft()
        d.role = ""
        v = validate_agent_draft(d, self.root)
        self.assertFalse(v.ok)

    def test_empty_responsibilities_rejected(self):
        d = self._draft()
        d.responsibilities = ""
        v = validate_agent_draft(d, self.root)
        self.assertFalse(v.ok)

    def test_duplicate_agent_warns(self):
        save_agent(self.root, self._draft())
        v = validate_agent_draft(self._draft(), self.root)
        self.assertTrue(v.already_exists)

    def test_save_without_overwrite_on_duplicate_raises(self):
        save_agent(self.root, self._draft())
        with self.assertRaises(FileExistsError):
            save_agent(self.root, self._draft())

    def test_save_with_overwrite_succeeds(self):
        save_agent(self.root, self._draft())
        result = save_agent(self.root, self._draft(), overwrite=True)
        self.assertTrue(Path(result["path"]).exists())

    def test_read_only_restriction_stated_by_default(self):
        rendered = render_agent_md(self._draft())
        self.assertIn("must NOT modify source files", rendered)

    def test_may_modify_source_reflected(self):
        d = self._draft()
        d.may_modify_source = True
        rendered = render_agent_md(d)
        self.assertIn("May modify source files.", rendered)

    def test_secret_redacted(self):
        d = self._draft()
        d.allowed_actions = "Use token=super-secret-abc123 to call the internal API."
        rendered = render_agent_md(d)
        self.assertNotIn("super-secret-abc123", rendered)

    def test_frontmatter_uses_name_and_description_only(self):
        rendered = render_agent_md(self._draft())
        frontmatter = rendered.split("---")[1]
        self.assertIn("name:", frontmatter)
        self.assertIn("description:", frontmatter)
        # No invented activation/tool-restriction fields.
        self.assertNotIn("activation:", frontmatter)
        self.assertNotIn("tools:", frontmatter)

    def test_preview_without_save_writes_nothing(self):
        draft = self._draft()
        render_agent_md(draft)
        self.assertFalse(agent_path(self.root, draft.name).exists())


if __name__ == "__main__":
    unittest.main()
