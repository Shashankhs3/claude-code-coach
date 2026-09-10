import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.analyzer.models import DimensionResult
from claude_code_coach.analyzer.scoring import bucket, score_prompt
from claude_code_coach.analyzer.task_classifier import TaskType


class TestBucket(unittest.TestCase):
    def test_bucket_boundaries(self):
        self.assertEqual(bucket(100), "EXCELLENT")
        self.assertEqual(bucket(90), "EXCELLENT")
        self.assertEqual(bucket(89), "GOOD")
        self.assertEqual(bucket(75), "GOOD")
        self.assertEqual(bucket(74), "NEEDS IMPROVEMENT")
        self.assertEqual(bucket(50), "NEEDS IMPROVEMENT")
        self.assertEqual(bucket(49), "POOR")
        self.assertEqual(bucket(0), "POOR")


class TestScoreProimpt(unittest.TestCase):
    def _all_clear(self, task_type):
        weights = {
            "goal": DimensionResult("clear"),
            "scope": DimensionResult("clear"),
            "investigation": DimensionResult("clear"),
            "constraints": DimensionResult("clear"),
            "done": DimensionResult("clear"),
            "output": DimensionResult("clear"),
        }
        return score_prompt(
            task_type, weights, breadth_level=0, overly_broad_read=False, low_effort=False
        )

    def test_all_clear_dimensions_score_100(self):
        score, rating = self._all_clear(TaskType.IMPLEMENTATION)
        self.assertEqual(score, 100)
        self.assertEqual(rating, "EXCELLENT")

    def test_low_effort_lands_in_poor_band(self):
        dims = {"goal": DimensionResult("missing")}
        score, rating = score_prompt(
            TaskType.IMPLEMENTATION, dims, breadth_level=0,
            overly_broad_read=False, low_effort=True,
        )
        self.assertTrue(10 <= score <= 30)
        self.assertEqual(rating, "POOR")

    def test_na_dimensions_do_not_hurt_information_requests(self):
        dims = {
            "goal": DimensionResult("clear"),
            "scope": DimensionResult("na"),
            "investigation": DimensionResult("na"),
            "output": DimensionResult("clear"),
        }
        score, rating = score_prompt(
            TaskType.INFORMATION, dims, breadth_level=0,
            overly_broad_read=False, low_effort=False,
        )
        self.assertGreaterEqual(score, 75)

    def test_breadth_penalty_reduces_score(self):
        dims = {
            "goal": DimensionResult("clear"),
            "scope": DimensionResult("clear"),
            "investigation": DimensionResult("clear"),
            "constraints": DimensionResult("clear"),
            "done": DimensionResult("clear"),
            "output": DimensionResult("clear"),
        }
        score_no_breadth, _ = score_prompt(
            TaskType.IMPLEMENTATION, dims, breadth_level=0,
            overly_broad_read=False, low_effort=False,
        )
        score_with_breadth, _ = score_prompt(
            TaskType.IMPLEMENTATION, dims, breadth_level=2,
            overly_broad_read=False, low_effort=False,
        )
        self.assertLess(score_with_breadth, score_no_breadth)

    def test_score_always_within_bounds(self):
        dims = {
            "goal": DimensionResult("missing"),
            "scope": DimensionResult("missing"),
            "investigation": DimensionResult("missing"),
            "constraints": DimensionResult("missing"),
            "done": DimensionResult("missing"),
            "output": DimensionResult("missing"),
        }
        score, _ = score_prompt(
            TaskType.MIXED, dims, breadth_level=2,
            overly_broad_read=True, low_effort=False,
        )
        self.assertTrue(0 <= score <= 100)


if __name__ == "__main__":
    unittest.main()
