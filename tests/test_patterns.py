import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.analytics.habits import all_time_opportunity_counts, habit_trends, today_stats
from claude_code_coach.analytics.patterns import (
    agent_candidates,
    claude_md_candidates,
    context_stats,
    skill_candidates,
)


def _row(prompt, task_type="review", opportunities=None, **overrides):
    base = {
        "id": overrides.get("id", 1),
        "timestamp": overrides.get("timestamp", "2026-01-01T00:00:00"),
        "prompt": prompt,
        "score": overrides.get("score", 70),
        "rating": overrides.get("rating", "GOOD"),
        "task_type": task_type,
        "goal_status": overrides.get("goal_status", "clear"),
        "scope_status": overrides.get("scope_status", "clear"),
        "investigation_status": overrides.get("investigation_status", "na"),
        "constraints_status": overrides.get("constraints_status", "na"),
        "done_status": overrides.get("done_status", "na"),
        "output_status": overrides.get("output_status", "na"),
        "good": overrides.get("good", []),
        "warnings": overrides.get("warnings", []),
        "opportunities": opportunities or [],
        "breadth_level": overrides.get("breadth_level", 0),
        "context_flag": overrides.get("context_flag", ""),
    }
    return base


class TestSkillCandidates(unittest.TestCase):
    def test_no_candidates_on_empty_history(self):
        self.assertEqual(skill_candidates([]), [])

    def test_repeated_review_workflow_becomes_candidate(self):
        rows = [
            _row(
                "Review API endpoint for authentication, validation, error handling and logging.",
                task_type="review",
                opportunities=[{"kind": "skill", "message": "x", "confidence": "medium"}],
                id=i,
            )
            for i in range(1, 5)
        ]
        candidates = skill_candidates(rows)
        self.assertGreaterEqual(len(candidates), 1)
        self.assertGreaterEqual(candidates[0]["occurrences"], 3)

    def test_single_occurrence_is_not_a_candidate(self):
        rows = [_row("Review the API for security issues.", task_type="review")]
        self.assertEqual(skill_candidates(rows), [])

    def test_unrelated_prompts_do_not_cluster(self):
        rows = [
            _row("Review the payments API for authentication issues.", task_type="review", id=1),
            _row("What color scheme does the frontend use?", task_type="information", id=2),
            _row("Explain the deployment pipeline.", task_type="explanation", id=3),
        ]
        self.assertEqual(skill_candidates(rows), [])


class TestAgentCandidates(unittest.TestCase):
    def test_requires_agent_opportunity(self):
        rows = [_row("Investigate the memory leak.", task_type="investigation", id=1)]
        self.assertEqual(agent_candidates(rows), [])

    def test_flagged_investigation_becomes_candidate(self):
        rows = [
            _row(
                "Investigate why memory usage grows over time across workers.",
                task_type="investigation",
                opportunities=[{"kind": "agent", "message": "x", "confidence": "high"}],
                id=1,
            )
        ]
        candidates = agent_candidates(rows)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["confidence"], "high")


class TestClaudeMdCandidates(unittest.TestCase):
    def test_requires_claude_md_opportunity(self):
        rows = [_row("Every API change must include tests.", task_type="mixed", id=1)]
        self.assertEqual(claude_md_candidates(rows), [])

    def test_flagged_rule_becomes_candidate(self):
        rows = [
            _row(
                "Every API change must include tests and migrations must be reviewed.",
                task_type="mixed",
                opportunities=[{"kind": "claude_md", "message": "x", "confidence": "medium"}],
                id=1,
            )
        ]
        self.assertEqual(len(claude_md_candidates(rows)), 1)


class TestContextStats(unittest.TestCase):
    def test_empty_history(self):
        stats = context_stats([])
        self.assertEqual(stats["total"], 0)
        self.assertFalse(stats["suggest_compaction"])

    def test_basic_aggregation(self):
        rows = [_row("Fix the typo in LoginButton.tsx.", score=90, id=1)]
        stats = context_stats(rows)
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["avg_score"], 90)


class TestHabitTrends(unittest.TestCase):
    def test_no_data(self):
        trends = habit_trends([])
        self.assertTrue(all(t["pct"] is None for t in trends))

    def test_all_clear_is_100_percent(self):
        rows = [_row("x", goal_status="clear", id=1), _row("y", goal_status="clear", id=2)]
        trends = habit_trends(rows)
        goal_trend = next(t for t in trends if t["label"] == "Goal clarity")
        self.assertEqual(goal_trend["pct"], 100)

    def test_na_rows_are_excluded_from_denominator(self):
        rows = [_row("x", done_status="na", id=1)]
        trends = habit_trends(rows)
        done_trend = next(t for t in trends if t["label"] == "Definition of done")
        self.assertIsNone(done_trend["pct"])


class TestTodayStats(unittest.TestCase):
    def test_empty(self):
        stats = today_stats([])
        self.assertEqual(stats["count"], 0)

    def test_opportunity_counts(self):
        rows = [_row("x", opportunities=[{"kind": "skill", "message": "m", "confidence": "low"}])]
        counts = all_time_opportunity_counts(rows)
        self.assertEqual(counts["skill"], 1)
        self.assertEqual(counts["agent"], 0)


if __name__ == "__main__":
    unittest.main()
