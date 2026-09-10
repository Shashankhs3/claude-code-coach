"""Tests for claude_code_coach/usage/ — real-transcript token usage and
estimated cost. All fixtures here are synthetic JSONL written to a temp
directory (never the real ~/.claude/projects/), matching the shape actually
observed in Claude Code's own transcripts.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.usage import pricing
from claude_code_coach.usage.transcript_parser import scan_all_transcripts, scan_transcript_file
from claude_code_coach.usage.usage_analyzer import build_usage_summary


def _assistant_line(*, model="claude-sonnet-5", input_tokens=100, output_tokens=50,
                     cache_read=0, cache_write_5m=0, cache_write_1h=0,
                     timestamp="2026-01-01T12:00:00.000Z", session_id="s1",
                     cwd="C:\\Projects\\Demo"):
    return json.dumps({
        "type": "assistant",
        "timestamp": timestamp,
        "sessionId": session_id,
        "cwd": cwd,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write_5m + cache_write_1h,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": cache_write_5m,
                    "ephemeral_1h_input_tokens": cache_write_1h,
                },
            },
        },
    })


class TestPricing(unittest.TestCase):
    def test_known_model_returns_price(self):
        self.assertIsNotNone(pricing.price_for_model("claude-sonnet-5"))

    def test_unknown_model_returns_none(self):
        self.assertIsNone(pricing.price_for_model("some-future-model-nobody-has-heard-of"))

    def test_cost_formula_matches_published_numbers(self):
        # Sonnet 5: $2/MTok input, $10/MTok output, cache read = 0.1x input,
        # 5m write = 1.25x input, 1h write = 2x input (verified against
        # Anthropic's published pricing + documented cache multipliers).
        cost = pricing.estimate_cost_usd(
            "claude-sonnet-5",
            input_tokens=1_000_000, output_tokens=1_000_000,
            cache_read_tokens=1_000_000, cache_write_5m_tokens=1_000_000,
            cache_write_1h_tokens=1_000_000,
        )
        expected = 2.0 + 10.0 + 0.2 + 2.5 + 4.0
        self.assertAlmostEqual(cost, expected, places=6)

    def test_unknown_model_cost_is_none_not_zero(self):
        cost = pricing.estimate_cost_usd(
            "some-future-model", input_tokens=1000, output_tokens=1000,
            cache_read_tokens=0, cache_write_5m_tokens=0, cache_write_1h_tokens=0,
        )
        self.assertIsNone(cost)


class TestTranscriptParser(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.projects_dir = Path(self._tmpdir.name) / "projects"
        self.projects_dir.mkdir()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write_transcript(self, project_name: str, session_id: str, lines: list[str]):
        project_dir = self.projects_dir / project_name
        project_dir.mkdir(exist_ok=True)
        (project_dir / f"{session_id}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_empty_projects_dir_returns_no_records(self):
        self.assertEqual(scan_all_transcripts(self.projects_dir), [])

    def test_missing_projects_dir_does_not_crash(self):
        missing = self.projects_dir / "does_not_exist"
        self.assertEqual(scan_all_transcripts(missing), [])

    def test_parses_real_shaped_line(self):
        self._write_transcript("proj-a", "s1", [
            _assistant_line(input_tokens=123, output_tokens=45, cache_read=6, cwd="C:\\A"),
        ])
        records = scan_all_transcripts(self.projects_dir)
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r.input_tokens, 123)
        self.assertEqual(r.output_tokens, 45)
        self.assertEqual(r.cache_read_tokens, 6)
        self.assertEqual(r.model, "claude-sonnet-5")
        self.assertEqual(r.cwd, "C:\\A")

    def test_malformed_line_is_skipped_not_crashed(self):
        self._write_transcript("proj-a", "s1", [
            "{not valid json",
            _assistant_line(input_tokens=10, output_tokens=5),
            "",
        ])
        records = scan_all_transcripts(self.projects_dir)
        self.assertEqual(len(records), 1)

    def test_line_without_usage_is_skipped(self):
        self._write_transcript("proj-a", "s1", [
            json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}),
        ])
        records = scan_all_transcripts(self.projects_dir)
        self.assertEqual(records, [])

    def test_synthetic_zero_usage_model_is_parsed_but_harmless(self):
        self._write_transcript("proj-a", "s1", [
            _assistant_line(model="<synthetic>", input_tokens=0, output_tokens=0),
        ])
        records = scan_all_transcripts(self.projects_dir)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].total_tokens, 0)

    def test_scan_transcript_file_missing_file_returns_empty(self):
        self.assertEqual(scan_transcript_file(self.projects_dir / "nope.jsonl"), [])

    def test_multiple_projects_and_sessions_all_scanned(self):
        self._write_transcript("proj-a", "s1", [_assistant_line(input_tokens=1)])
        self._write_transcript("proj-b", "s2", [_assistant_line(input_tokens=2)])
        self._write_transcript("proj-b", "s3", [_assistant_line(input_tokens=3)])
        records = scan_all_transcripts(self.projects_dir)
        self.assertEqual(len(records), 3)


class TestUsageAnalyzer(unittest.TestCase):
    def test_totals_sum_correctly_across_records(self):
        from claude_code_coach.usage.transcript_parser import UsageRecord

        records = [
            UsageRecord(
                timestamp="2026-01-01T00:00:00.000Z", model="claude-sonnet-5",
                session_id="s1", project_dir="proj-a", cwd="C:\\A",
                input_tokens=100, output_tokens=50, cache_read_tokens=10,
                cache_write_5m_tokens=5, cache_write_1h_tokens=0,
            ),
            UsageRecord(
                timestamp="2026-01-01T01:00:00.000Z", model="claude-sonnet-5",
                session_id="s1", project_dir="proj-a", cwd="C:\\A",
                input_tokens=200, output_tokens=75, cache_read_tokens=20,
                cache_write_5m_tokens=0, cache_write_1h_tokens=8,
            ),
        ]
        summary = build_usage_summary(records)
        self.assertEqual(summary.all_time.input_tokens, 300)
        self.assertEqual(summary.all_time.output_tokens, 125)
        self.assertEqual(summary.all_time.cache_read_tokens, 30)
        self.assertEqual(summary.all_time.cache_write_5m_tokens, 5)
        self.assertEqual(summary.all_time.cache_write_1h_tokens, 8)
        self.assertEqual(summary.session_count, 1)
        self.assertGreater(summary.all_time.cost_usd, 0)
        self.assertEqual(summary.all_time.unpriced_tokens, 0)

    def test_unknown_model_tokens_are_unpriced_not_ignored(self):
        from claude_code_coach.usage.transcript_parser import UsageRecord

        records = [
            UsageRecord(
                timestamp="2026-01-01T00:00:00.000Z", model="some-future-model",
                session_id="s1", project_dir="proj-a", cwd="C:\\A",
                input_tokens=1000, output_tokens=500, cache_read_tokens=0,
                cache_write_5m_tokens=0, cache_write_1h_tokens=0,
            ),
        ]
        summary = build_usage_summary(records)
        self.assertEqual(summary.all_time.total_tokens, 1500)
        self.assertEqual(summary.all_time.cost_usd, 0.0)
        self.assertEqual(summary.all_time.unpriced_tokens, 1500)

    def test_empty_records_produces_empty_summary_not_crash(self):
        summary = build_usage_summary([])
        self.assertEqual(summary.all_time.total_tokens, 0)
        self.assertEqual(summary.session_count, 0)
        self.assertEqual(summary.by_project, {})
        self.assertEqual(summary.by_model, {})

    def test_by_project_groups_by_project_dir_not_raw_cwd(self):
        # Same project_dir, two different cwd values recorded within it
        # (e.g. the user cd'd into a subdirectory) -- must still be ONE
        # project row, not two.
        from claude_code_coach.usage.transcript_parser import UsageRecord

        records = [
            UsageRecord(
                timestamp="2026-01-01T00:00:00.000Z", model="claude-sonnet-5",
                session_id="s1", project_dir="e--myproj", cwd="E:\\myproj",
                input_tokens=100, output_tokens=0, cache_read_tokens=0,
                cache_write_5m_tokens=0, cache_write_1h_tokens=0,
            ),
            UsageRecord(
                timestamp="2026-01-01T00:01:00.000Z", model="claude-sonnet-5",
                session_id="s1", project_dir="e--myproj", cwd="E:\\myproj\\sub",
                input_tokens=50, output_tokens=0, cache_read_tokens=0,
                cache_write_5m_tokens=0, cache_write_1h_tokens=0,
            ),
            UsageRecord(
                timestamp="2026-01-01T00:02:00.000Z", model="claude-sonnet-5",
                session_id="s1", project_dir="e--myproj", cwd="E:\\myproj",
                input_tokens=25, output_tokens=0, cache_read_tokens=0,
                cache_write_5m_tokens=0, cache_write_1h_tokens=0,
            ),
        ]
        summary = build_usage_summary(records)
        self.assertEqual(len(summary.by_project), 1)
        # Labeled with the most frequent real cwd seen (E:\myproj, 2 of 3).
        label = next(iter(summary.by_project))
        self.assertEqual(label, "E:\\myproj")
        self.assertEqual(summary.by_project[label].input_tokens, 175)

    def test_by_model_breakdown(self):
        from claude_code_coach.usage.transcript_parser import UsageRecord

        records = [
            UsageRecord(
                timestamp="2026-01-01T00:00:00.000Z", model="claude-sonnet-5",
                session_id="s1", project_dir="p", cwd="C:\\p",
                input_tokens=100, output_tokens=0, cache_read_tokens=0,
                cache_write_5m_tokens=0, cache_write_1h_tokens=0,
            ),
            UsageRecord(
                timestamp="2026-01-01T00:00:00.000Z", model="claude-opus-5",
                session_id="s2", project_dir="p", cwd="C:\\p",
                input_tokens=200, output_tokens=0, cache_read_tokens=0,
                cache_write_5m_tokens=0, cache_write_1h_tokens=0,
            ),
        ]
        summary = build_usage_summary(records)
        self.assertEqual(set(summary.by_model), {"claude-sonnet-5", "claude-opus-5"})
        self.assertEqual(summary.by_model["claude-sonnet-5"].input_tokens, 100)
        self.assertEqual(summary.by_model["claude-opus-5"].input_tokens, 200)


if __name__ == "__main__":
    unittest.main()
