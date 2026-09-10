import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.database import db as db_module
from claude_code_coach.database.migrations import ensure_schema


class TempDbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_path = db_module.DB_PATH
        db_module.DB_PATH = Path(self._tmpdir.name) / "test_coach.db"

    def tearDown(self):
        db_module.DB_PATH = self._original_path
        self._tmpdir.cleanup()


class TestSafeScore(unittest.TestCase):
    def test_int(self):
        self.assertEqual(db_module.safe_score(42), 42)

    def test_string_int(self):
        self.assertEqual(db_module.safe_score("42"), 42)

    def test_string_float(self):
        self.assertEqual(db_module.safe_score("42.7"), 43)

    def test_none(self):
        self.assertEqual(db_module.safe_score(None), 0)

    def test_garbage_string(self):
        self.assertEqual(db_module.safe_score("not a number"), 0)

    def test_clamped_high(self):
        self.assertEqual(db_module.safe_score(999), 100)

    def test_clamped_low(self):
        self.assertEqual(db_module.safe_score(-50), 0)

    def test_bool_is_not_a_score(self):
        self.assertEqual(db_module.safe_score(True), 0)


class TestDatabaseLifecycle(TempDbTestCase):
    def test_init_creates_schema(self):
        db_module.init_db()
        self.assertTrue(db_module.DB_PATH.exists())
        self.assertEqual(db_module.count_prompts(), 0)

    def test_insert_and_fetch(self):
        db_module.init_db()
        record = {
            "timestamp": "2026-01-01T00:00:00",
            "prompt": "Fix the login timeout in src/auth/login.ts.",
            "score": 88,
            "rating": "GOOD",
            "task_type": "debugging",
            "goal_status": "clear",
            "scope_status": "clear",
            "investigation_status": "na",
            "constraints_status": "missing",
            "done_status": "clear",
            "output_status": "na",
            "good": ["Clear goal"],
            "warnings": ["No constraints"],
            "opportunities": [{"kind": "agent", "message": "x", "confidence": "low"}],
            "breadth_level": 0,
            "context_flag": "",
        }
        row_id = db_module.insert_prompt(record)
        self.assertIsInstance(row_id, int)

        fetched = db_module.fetch_prompt(row_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["score"], 88)
        self.assertEqual(fetched["good"], ["Clear goal"])
        self.assertEqual(fetched["opportunities"][0]["kind"], "agent")

        all_rows = db_module.fetch_all_prompts()
        self.assertEqual(len(all_rows), 1)
        self.assertEqual(db_module.count_prompts(), 1)

    def test_fetch_missing_prompt_returns_none(self):
        db_module.init_db()
        self.assertIsNone(db_module.fetch_prompt(999))

    def test_clear_all(self):
        db_module.init_db()
        db_module.insert_prompt({
            "timestamp": "2026-01-01T00:00:00", "prompt": "x", "score": 50,
        })
        self.assertEqual(db_module.count_prompts(), 1)
        db_module.clear_all()
        self.assertEqual(db_module.count_prompts(), 0)
        self.assertEqual(db_module.fetch_all_prompts(), [])

    def test_clear_empty_database_does_not_crash(self):
        db_module.init_db()
        db_module.clear_all()
        self.assertEqual(db_module.count_prompts(), 0)

    def test_db_info(self):
        db_module.init_db()
        info = db_module.db_info()
        self.assertIn("path", info)
        self.assertIn("prompt_count", info)

    def test_export_and_import_round_trip(self):
        db_module.init_db()
        db_module.insert_prompt({
            "timestamp": "2026-01-01T00:00:00", "prompt": "Round trip prompt",
            "score": 70, "rating": "GOOD",
        })
        export_path = Path(self._tmpdir.name) / "export.json"
        exported = db_module.export_json(export_path)
        self.assertEqual(exported, 1)

        db_module.clear_all()
        self.assertEqual(db_module.count_prompts(), 0)

        imported = db_module.import_json(export_path)
        self.assertEqual(imported, 1)
        self.assertEqual(db_module.count_prompts(), 1)

    def test_import_rejects_non_list_json(self):
        db_module.init_db()
        bad_path = Path(self._tmpdir.name) / "bad.json"
        bad_path.write_text('{"not": "a list"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            db_module.import_json(bad_path)


class TestMigrations(TempDbTestCase):
    def test_fresh_db_gets_current_schema(self):
        conn = sqlite3.connect(db_module.DB_PATH)
        ensure_schema(conn)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(prompts)")}
        self.assertIn("goal_status", cols)
        self.assertIn("opportunities_json", cols)
        conn.close()

    def test_legacy_schema_is_migrated_without_crashing(self):
        conn = sqlite3.connect(db_module.DB_PATH)
        conn.execute(
            """
            CREATE TABLE prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                prompt TEXT NOT NULL,
                score TEXT NOT NULL,
                rating TEXT NOT NULL,
                good_count INTEGER NOT NULL,
                warning_count INTEGER NOT NULL,
                opportunities TEXT NOT NULL
            )
            """
        )
        # Legacy prototype bug: score stored as a string.
        conn.execute(
            "INSERT INTO prompts (created_at, prompt, score, rating, good_count, "
            "warning_count, opportunities) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("2025-01-01T00:00:00", "Legacy prompt", "73", "GOOD", 2, 1,
             "Consider a Skill\nConsider CLAUDE.md"),
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(db_module.DB_PATH)
        ensure_schema(conn)
        row = conn.execute("SELECT * FROM prompts").fetchone()
        conn.close()

        cols = {row[1] for row in sqlite3.connect(db_module.DB_PATH).execute(
            "PRAGMA table_info(prompts)"
        )}
        self.assertIn("goal_status", cols)

        # Score must now be a real int, not the legacy string.
        rows = db_module.fetch_all_prompts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], 73)
        self.assertIsInstance(rows[0]["score"], int)
        # Legacy score + int arithmetic must not crash (the exact V2 bug).
        total = sum(r["score"] for r in rows) + 10
        self.assertEqual(total, 83)

    def test_v2_style_db_gets_v3_environment_tables_too(self):
        conn = sqlite3.connect(db_module.DB_PATH)
        conn.execute(
            """
            CREATE TABLE prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL, prompt TEXT NOT NULL, score TEXT NOT NULL,
                rating TEXT NOT NULL, good_count INTEGER NOT NULL,
                warning_count INTEGER NOT NULL, opportunities TEXT NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(db_module.DB_PATH)
        ensure_schema(conn)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        for expected in ("environment_scans", "claude_md_metadata", "skills_metadata",
                          "agents_metadata", "mcp_metadata", "app_settings"):
            self.assertIn(expected, tables)


class TestEnvironmentSettingsStorage(TempDbTestCase):
    def test_get_setting_missing_returns_default(self):
        db_module.init_db()
        self.assertIsNone(db_module.get_setting("nope"))
        self.assertEqual(db_module.get_setting("nope", "fallback"), "fallback")

    def test_set_and_get_setting_round_trip(self):
        db_module.init_db()
        db_module.set_setting("project_root", "E:/some/project")
        self.assertEqual(db_module.get_setting("project_root"), "E:/some/project")

    def test_set_setting_overwrites(self):
        db_module.init_db()
        db_module.set_setting("scan_on_startup", "0")
        db_module.set_setting("scan_on_startup", "1")
        self.assertEqual(db_module.get_setting("scan_on_startup"), "1")

    def test_fetch_environment_snapshot_none_when_never_scanned(self):
        db_module.init_db()
        self.assertIsNone(db_module.fetch_environment_snapshot())

    def test_save_and_fetch_environment_snapshot_round_trip(self):
        from claude_code_coach.providers.models import (
            AgentInfo, ClaudeMdInfo, EnvironmentSnapshot, McpServerInfo, SkillInfo, Source,
        )
        db_module.init_db()
        snapshot = EnvironmentSnapshot(
            scanned_at="2026-01-01T00:00:00",
            project_root="E:/project",
            claude_md=[ClaudeMdInfo(path="E:/project/CLAUDE.md", scope=Source.PROJECT,
                                     size_bytes=42, modified="2026-01-01T00:00:00",
                                     preview="hello")],
            skills=[SkillInfo(name="s1", path="E:/s1/SKILL.md", description="d",
                               source=Source.PROJECT, modified="2026-01-01T00:00:00")],
            agents=[AgentInfo(name="a1", path="E:/a1.md", description="d",
                               source=Source.USER, modified="2026-01-01T00:00:00")],
            mcp_servers=[McpServerInfo(name="m1", server_type="stdio", source=Source.PROJECT,
                                        config_path="E:/.mcp.json", enabled=True)],
            errors=["one warning"],
        )
        db_module.save_environment_snapshot(snapshot)

        fetched = db_module.fetch_environment_snapshot()
        self.assertEqual(fetched["skills_count"], 1)
        self.assertEqual(fetched["skills"][0]["name"], "s1")
        self.assertEqual(fetched["agents"][0]["source"], "user")
        self.assertEqual(fetched["mcp_servers"][0]["enabled"], 1)
        self.assertEqual(fetched["errors"], ["one warning"])

    def test_rescanning_replaces_previous_snapshot(self):
        from claude_code_coach.providers.models import EnvironmentSnapshot, SkillInfo, Source
        db_module.init_db()
        db_module.save_environment_snapshot(EnvironmentSnapshot(
            scanned_at="2026-01-01T00:00:00", project_root="E:/project",
            skills=[SkillInfo(name="old", path="x", description="", source=Source.PROJECT,
                               modified="")],
        ))
        db_module.save_environment_snapshot(EnvironmentSnapshot(
            scanned_at="2026-01-02T00:00:00", project_root="E:/project", skills=[],
        ))
        fetched = db_module.fetch_environment_snapshot()
        self.assertEqual(fetched["skills"], [])

    def test_clear_all_wipes_environment_data_but_keeps_settings(self):
        from claude_code_coach.providers.models import EnvironmentSnapshot, SkillInfo, Source
        db_module.init_db()
        db_module.set_setting("project_root", "E:/keep-me")
        db_module.save_environment_snapshot(EnvironmentSnapshot(
            scanned_at="2026-01-01T00:00:00", project_root="E:/keep-me",
            skills=[SkillInfo(name="s", path="x", description="", source=Source.PROJECT,
                               modified="")],
        ))
        db_module.clear_all()
        self.assertIsNone(db_module.fetch_environment_snapshot())
        self.assertEqual(db_module.get_setting("project_root"), "E:/keep-me")


if __name__ == "__main__":
    unittest.main()
