import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.database import db as db_module
from claude_code_coach.runtime import event_parser, hook_installer, runtime_analyzer, session_title
from claude_code_coach.runtime.event_source import HookFileEventSource, NullRuntimeEventSource
from claude_code_coach.runtime.models import ConnectionState, RuntimeEvent, RuntimeEventType


class TempDbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_path = db_module.DB_PATH
        db_module.DB_PATH = Path(self._tmpdir.name) / "test_coach.db"

    def tearDown(self):
        db_module.DB_PATH = self._original_path
        self._tmpdir.cleanup()


class TestEventParser(unittest.TestCase):
    def test_unknown_event_name_does_not_crash(self):
        event = event_parser.parse_hook_payload({"hook_event_name": "SomethingNew", "session_id": "s"})
        self.assertEqual(event.event_type, RuntimeEventType.UNKNOWN)

    def test_missing_session_id_defaults_safely(self):
        event = event_parser.parse_hook_payload({"hook_event_name": "Stop"})
        self.assertEqual(event.session_id, "unknown")

    def test_prompt_content_not_stored_by_default(self):
        event = event_parser.parse_hook_payload({
            "hook_event_name": "UserPromptSubmit", "session_id": "s",
            "prompt": "Fix the login bug in src/auth.py.",
        })
        self.assertIsNone(event.content)
        self.assertIn("word_count", event.metadata)
        self.assertIn("tokens", event.metadata)

    def test_prompt_content_stored_when_opted_in(self):
        event = event_parser.parse_hook_payload({
            "hook_event_name": "UserPromptSubmit", "session_id": "s", "prompt": "Fix the bug.",
        }, collect_content=True)
        self.assertEqual(event.content, "Fix the bug.")

    def test_secret_in_bash_command_is_redacted(self):
        event = event_parser.parse_hook_payload({
            "hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "Bash",
            "tool_input": {"command": "curl -H 'API_KEY=super-secret-value' example.com"},
        })
        self.assertNotIn("super-secret-value", event.metadata["command"])

    def test_derives_task_classification_from_analyzer(self):
        event = event_parser.parse_hook_payload({
            "hook_event_name": "UserPromptSubmit", "session_id": "s",
            "prompt": "Fix the login timeout in src/auth/login.ts. Done when tests pass.",
        })
        self.assertEqual(event.metadata["scope_status"], "clear")

    def test_non_dict_payload_does_not_crash_parser_call_site(self):
        # parse_hook_payload assumes a dict; the receiver guards non-dict input
        # before calling it (tested separately) — this just checks empty dict.
        event = event_parser.parse_hook_payload({})
        self.assertEqual(event.event_type, RuntimeEventType.UNKNOWN)


class TestHookReceiverSubprocess(unittest.TestCase):
    """Invokes the real script via subprocess+stdin, exactly as Claude Code would."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.fake_home = Path(self._tmpdir.name) / "home"
        self.fake_home.mkdir()
        self.receiver = Path("claude_code_coach/runtime/hook_receiver.py").resolve()
        self.env = dict(os.environ)
        self.env["USERPROFILE"] = str(self.fake_home)
        self.env["HOME"] = str(self.fake_home)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _fire(self, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.receiver)], input=json.dumps(payload),
            capture_output=True, text=True, env=self.env, timeout=30,
        )

    def test_always_exits_zero_and_silent_on_good_input(self):
        result = self._fire({"session_id": "s1", "hook_event_name": "Stop",
                              "last_assistant_message": "done"})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_never_disrupts_session_on_malformed_json(self):
        result = subprocess.run(
            [sys.executable, str(self.receiver)], input="{not valid json",
            capture_output=True, text=True, env=self.env, timeout=30,
        )
        self.assertEqual(result.returncode, 0)

    def test_never_disrupts_session_on_empty_stdin(self):
        result = subprocess.run(
            [sys.executable, str(self.receiver)], input="",
            capture_output=True, text=True, env=self.env, timeout=30,
        )
        self.assertEqual(result.returncode, 0)

    def test_event_actually_written_to_isolated_home(self):
        self._fire({"session_id": "s1", "hook_event_name": "SessionStart", "cwd": "/proj"})
        events_dir = self.fake_home / ".claude_code_coach" / "runtime_events"
        self.assertTrue(events_dir.is_dir())
        files = list(events_dir.glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        line = json.loads(files[0].read_text(encoding="utf-8").strip())
        self.assertEqual(line["event_type"], "SessionStart")

    def test_never_leaks_into_real_home(self):
        real_home_events = Path.home() / ".claude_code_coach" / "runtime_events"
        before = set(real_home_events.glob("*.jsonl")) if real_home_events.is_dir() else set()
        self._fire({"session_id": "isolation-check", "hook_event_name": "Stop",
                    "last_assistant_message": "x"})
        after = set(real_home_events.glob("*.jsonl")) if real_home_events.is_dir() else set()
        self.assertEqual(before, after)


class TestEventSourceDrain(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.events_dir = Path(self._tmpdir.name) / "runtime_events"
        self.events_dir.mkdir()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write_line(self, session_id: str, event_type: str, **extra):
        path = self.events_dir / f"{session_id}.jsonl"
        line = {"received_at": "2026-01-01T00:00:00", "session_id": session_id,
                "event_type": event_type, "tool_name": extra.get("tool_name"),
                "metadata": extra.get("metadata", {}), "content": None}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")

    def test_empty_directory_returns_nothing(self):
        source = HookFileEventSource(self.events_dir)
        self.assertEqual(source.poll(), [])

    def test_missing_directory_does_not_crash(self):
        source = HookFileEventSource(self.events_dir / "does_not_exist")
        self.assertEqual(source.poll(), [])

    def test_drains_and_removes_file(self):
        self._write_line("s1", "Stop")
        source = HookFileEventSource(self.events_dir)
        events = source.poll()
        self.assertEqual(len(events), 1)
        self.assertEqual(list(self.events_dir.glob("*.jsonl")), [])

    def test_second_poll_is_empty_no_duplication(self):
        self._write_line("s1", "Stop")
        source = HookFileEventSource(self.events_dir)
        source.poll()
        self.assertEqual(source.poll(), [])

    def test_new_source_instance_after_drain_does_not_reread(self):
        """Simulates an app restart: a fresh HookFileEventSource (no in-memory
        state carried over) must not re-ingest already-drained content."""
        self._write_line("s1", "Stop")
        HookFileEventSource(self.events_dir).poll()
        fresh_source = HookFileEventSource(self.events_dir)
        self.assertEqual(fresh_source.poll(), [])

    def test_malformed_line_is_skipped_not_crashed(self):
        path = self.events_dir / "s1.jsonl"
        path.write_text('not json at all\n{"received_at":"x","session_id":"s1",'
                         '"event_type":"Stop","tool_name":null,"metadata":{},"content":null}\n',
                         encoding="utf-8")
        events = HookFileEventSource(self.events_dir).poll()
        self.assertEqual(len(events), 1)

    def test_null_source_reports_unavailable(self):
        source = NullRuntimeEventSource()
        self.assertFalse(source.is_available())
        self.assertEqual(source.poll(), [])


class TestHookInstaller(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self._tmpdir.name) / "settings.json"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_install_on_fresh_file(self):
        result = hook_installer.install_hooks(self.settings_path)
        self.assertTrue(self.settings_path.exists())
        self.assertEqual(set(result["added_events"]), set(hook_installer.HOOK_EVENTS))
        self.assertTrue(hook_installer.hooks_installed_in(self.settings_path))

    def test_install_is_idempotent(self):
        hook_installer.install_hooks(self.settings_path)
        second = hook_installer.install_hooks(self.settings_path)
        self.assertEqual(second["added_events"], [])

    def test_install_preserves_existing_unrelated_settings(self):
        self.settings_path.write_text(json.dumps({
            "hooks": {"Stop": [{"matcher": "*", "hooks": [
                {"type": "command", "command": "/bin/my-other-hook.sh"}
            ]}]},
            "someOtherSetting": True,
        }), encoding="utf-8")

        hook_installer.install_hooks(self.settings_path)
        data = json.loads(self.settings_path.read_text(encoding="utf-8"))

        self.assertTrue(data["someOtherSetting"])
        stop_hooks = [h for group in data["hooks"]["Stop"] for h in group["hooks"]]
        self.assertTrue(any(h.get("command") == "/bin/my-other-hook.sh" for h in stop_hooks))
        self.assertTrue(any("hook_receiver.py" in str(h.get("args", [])) for h in stop_hooks))

    def test_uninstall_removes_only_our_entries(self):
        self.settings_path.write_text(json.dumps({
            "hooks": {"Stop": [{"matcher": "*", "hooks": [
                {"type": "command", "command": "/bin/my-other-hook.sh"}
            ]}]},
        }), encoding="utf-8")
        hook_installer.install_hooks(self.settings_path)
        hook_installer.uninstall_hooks(self.settings_path)

        data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertFalse(hook_installer.hooks_installed_in(self.settings_path))
        stop_hooks = [h for group in data["hooks"]["Stop"] for h in group["hooks"]]
        self.assertTrue(any(h.get("command") == "/bin/my-other-hook.sh" for h in stop_hooks))

    def test_uninstall_on_never_installed_file_is_a_safe_noop(self):
        result = hook_installer.uninstall_hooks(self.settings_path)
        self.assertEqual(result["removed_events"], [])

    def test_malformed_existing_file_raises_instead_of_overwriting(self):
        self.settings_path.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(ValueError):
            hook_installer.install_hooks(self.settings_path)
        # File must be untouched.
        self.assertEqual(self.settings_path.read_text(encoding="utf-8"), "{not valid json")

    def test_write_is_atomic_no_stray_temp_files_left(self):
        hook_installer.install_hooks(self.settings_path)
        leftovers = list(self.settings_path.parent.glob(".coach_settings_*"))
        self.assertEqual(leftovers, [])


class TestHookInstallerFrozen(unittest.TestCase):
    """A packaged build must never write a hook Claude Code can't actually
    invoke — sys.executable there is this app's own GUI exe, and this
    module's own __file__ resolves inside a temp dir PyInstaller deletes on
    exit (see hook_installer.py's module docstring). These simulate
    `sys.frozen` rather than actually freezing a build in the test suite."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self._tmpdir.name) / "settings.json"
        self._frozen_exe = Path(self._tmpdir.name) / "app" / "ClaudeCodeCoach.exe"
        self._frozen_exe.parent.mkdir(parents=True, exist_ok=True)
        self._patches = [
            unittest.mock.patch.object(sys, "frozen", True, create=True),
            unittest.mock.patch.object(sys, "executable", str(self._frozen_exe)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmpdir.cleanup()

    def test_frozen_command_is_the_companion_exe_not_this_gui_exe(self):
        command, args = hook_installer.hook_command()
        self.assertNotEqual(command, str(self._frozen_exe))
        self.assertTrue(command.endswith("hook_receiver.exe"))
        self.assertEqual(args, [])

    def test_frozen_receiver_path_is_derived_from_the_exe_not_this_module(self):
        # The bug this guards against: deriving the receiver path from this
        # *module's* __file__ (as source mode does) would, under a frozen
        # --onefile build, point inside a per-run PyInstaller extraction dir
        # that's deleted the moment this process exits. Deriving it from
        # sys.executable's own (persistent, installed) location instead
        # means the same path comes back every time, computed independently
        # by install/uninstall/status at completely different moments.
        expected = self._frozen_exe.parent / "hook_receiver" / "hook_receiver.exe"
        first, _ = hook_installer.hook_command()
        second, _ = hook_installer.hook_command()
        self.assertEqual(first, str(expected))
        self.assertEqual(first, second)

    def test_install_and_uninstall_agree_when_frozen(self):
        hook_installer.install_hooks(self.settings_path)
        self.assertTrue(hook_installer.hooks_installed_in(self.settings_path))
        data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        stop_hooks = [h for group in data["hooks"]["Stop"] for h in group["hooks"]]
        self.assertTrue(any(h.get("command", "").endswith("hook_receiver.exe") for h in stop_hooks))
        self.assertTrue(all(h.get("args") == [] for h in stop_hooks if "hook_receiver.exe" in h.get("command", "")))

        hook_installer.uninstall_hooks(self.settings_path)
        self.assertFalse(hook_installer.hooks_installed_in(self.settings_path))


class TestRuntimeAnalyzerBasics(unittest.TestCase):
    def test_no_events_produces_no_signals(self):
        self.assertEqual(runtime_analyzer.search_first_signal([], None), [])

    def test_no_compactions_produces_no_context_signal(self):
        self.assertEqual(runtime_analyzer.context_hygiene_signal({"compactions": 0}), [])

    def test_repeated_instructions_below_threshold_is_silent(self):
        events = [
            event_parser.parse_hook_payload({
                "hook_event_name": "UserPromptSubmit", "session_id": f"s{i}",
                "prompt": "Review API endpoint for authentication and validation.",
            })
            for i in range(2)
        ]
        self.assertEqual(runtime_analyzer.repeated_instructions_signal(events), [])


class TestRuntimeDatabaseAndMigration(TempDbTestCase):
    def test_v3_db_gets_v4_runtime_tables(self):
        import sqlite3
        db_module.init_db()  # creates a fresh (already-v4) DB

        conn = sqlite3.connect(db_module.DB_PATH)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        conn.close()
        self.assertIn("runtime_events", tables)
        self.assertIn("runtime_sessions", tables)

    def test_clear_all_wipes_runtime_data(self):
        from claude_code_coach.runtime.models import RuntimeEvent, RuntimeEventType as T
        db_module.init_db()
        db_module.insert_runtime_event(RuntimeEvent(
            id=None, received_at="2026-01-01T00:00:00", session_id="s1",
            event_type=T.STOP, metadata={},
        ))
        self.assertEqual(len(db_module.list_runtime_sessions()), 1)
        db_module.clear_all()
        self.assertEqual(db_module.list_runtime_sessions(), [])

    def test_purge_older_than_removes_stale_sessions(self):
        from claude_code_coach.runtime.models import RuntimeEvent, RuntimeEventType as T
        db_module.init_db()
        db_module.insert_runtime_event(RuntimeEvent(
            id=None, received_at="2000-01-01T00:00:00", session_id="old",
            event_type=T.STOP, metadata={},
        ))
        purged = db_module.purge_runtime_events_older_than(7)
        self.assertGreaterEqual(purged, 1)
        self.assertIsNone(db_module.get_runtime_session("old"))


class TestRuntimeCoachStatus(TempDbTestCase):
    """`HookFileEventSource` pointed at an empty temp dir is used here — it's
    the real, is_available()=True mechanism, just with nothing in it yet.
    `NullRuntimeEventSource` is reserved for the deliberate "paused" state
    (spec section 24), tested separately below.
    """

    def _real_but_empty_source(self):
        events_dir = Path(self._tmpdir.name) / "runtime_events"
        events_dir.mkdir(exist_ok=True)
        return HookFileEventSource(events_dir)

    def test_not_configured_when_hooks_never_installed(self):
        db_module.init_db()
        from claude_code_coach.runtime.runtime_coach import RuntimeCoach
        coach = RuntimeCoach(source=self._real_but_empty_source())
        status = coach.status()
        self.assertEqual(status.state, ConnectionState.NOT_CONFIGURED)
        self.assertIsNone(status.current_session)

    def test_configured_but_no_events_yet(self):
        db_module.init_db()
        db_module.set_setting("runtime_hooks_installed", "1")
        from claude_code_coach.runtime.runtime_coach import RuntimeCoach
        coach = RuntimeCoach(source=self._real_but_empty_source())
        status = coach.status()
        self.assertEqual(status.state, ConnectionState.CONFIGURED)

    def test_live_when_recent_event_exists(self):
        from datetime import datetime
        from claude_code_coach.runtime.models import RuntimeEvent, RuntimeEventType as T
        db_module.init_db()
        db_module.insert_runtime_event(RuntimeEvent(
            id=None, received_at=datetime.now().isoformat(timespec="seconds"),
            session_id="s1", event_type=T.USER_PROMPT_SUBMIT,
            metadata={"word_count": 3, "tokens": [], "task_type": "implementation",
                      "scope_status": "missing", "breadth_level": 0, "vague_goal": False},
        ))
        from claude_code_coach.runtime.runtime_coach import RuntimeCoach
        coach = RuntimeCoach(source=self._real_but_empty_source())
        status = coach.status()
        self.assertEqual(status.state, ConnectionState.LIVE)
        self.assertIsNotNone(status.current_session)
        self.assertEqual(status.current_session.prompts, 1)

    def test_paused_source_reports_unavailable_and_never_polls(self):
        # This is the deliberate "Runtime Coach: OFF" pathway (spec section
        # 24) — the controller swaps in NullRuntimeEventSource when paused.
        db_module.init_db()
        from claude_code_coach.runtime.runtime_coach import RuntimeCoach
        coach = RuntimeCoach(source=NullRuntimeEventSource())
        self.assertEqual(coach.poll_and_store(), 0)
        self.assertEqual(coach.status().state, ConnectionState.UNAVAILABLE)

    def test_session_title_falls_back_to_task_type_by_default(self):
        # Content collection is off by default (event_parser.py), so the
        # real V4 path from a real hook payload should land on the
        # task_type tier, never crash, and never require the raw prompt.
        from claude_code_coach.runtime.event_parser import parse_hook_payload
        from claude_code_coach.runtime.runtime_coach import RuntimeCoach
        db_module.init_db()
        event = parse_hook_payload({
            "hook_event_name": "UserPromptSubmit", "session_id": "s1",
            "prompt": "Please help me debug why the build keeps failing.",
        }, collect_content=False)
        self.assertIsNone(event.content)
        db_module.insert_runtime_event(event)

        coach = RuntimeCoach(source=self._real_but_empty_source())
        status = coach.status()
        self.assertIsNotNone(status.current_session)
        self.assertEqual(status.current_session.title, "Debugging session")

    def test_session_title_uses_real_text_when_opted_in(self):
        from claude_code_coach.runtime.event_parser import parse_hook_payload
        from claude_code_coach.runtime.runtime_coach import RuntimeCoach
        db_module.init_db()
        event = parse_hook_payload({
            "hook_event_name": "UserPromptSubmit", "session_id": "s1",
            "prompt": "Fix the Dashboard warning shown on reconnect.",
        }, collect_content=True)
        db_module.insert_runtime_event(event)

        coach = RuntimeCoach(source=self._real_but_empty_source())
        status = coach.status()
        self.assertEqual(status.current_session.title, "Fix the Dashboard warning shown on reconnect")

    def test_session_traversal_no_cross_session_leakage(self):
        # Two distinct sessions, each with its own first prompt — looking up
        # session A must never return session B's title/stats, and vice
        # versa (spec section 14/15).
        from claude_code_coach.runtime.event_parser import parse_hook_payload
        from claude_code_coach.runtime.runtime_coach import RuntimeCoach
        db_module.init_db()
        db_module.insert_runtime_event(parse_hook_payload({
            "hook_event_name": "UserPromptSubmit", "session_id": "session-a",
            "prompt": "Fix the Dashboard warning.",
        }, collect_content=True))
        db_module.insert_runtime_event(parse_hook_payload({
            "hook_event_name": "UserPromptSubmit", "session_id": "session-b",
            "prompt": "Investigate the login test failure.",
        }, collect_content=True))

        events_a = [
            RuntimeEvent(id=r.get("id"), received_at=r["received_at"], session_id=r["session_id"],
                         event_type=RuntimeEventType.from_hook_name(r["event_type"]),
                         tool_name=r.get("tool_name") or None, metadata=r.get("metadata") or {},
                         content=r.get("content"))
            for r in db_module.fetch_runtime_events("session-a")
        ]
        events_b = [
            RuntimeEvent(id=r.get("id"), received_at=r["received_at"], session_id=r["session_id"],
                         event_type=RuntimeEventType.from_hook_name(r["event_type"]),
                         tool_name=r.get("tool_name") or None, metadata=r.get("metadata") or {},
                         content=r.get("content"))
            for r in db_module.fetch_runtime_events("session-b")
        ]

        title_a = session_title.title_for_session(events_a)
        title_b = session_title.title_for_session(events_b)

        self.assertEqual(title_a, "Fix the Dashboard warning")
        self.assertEqual(title_b, "Investigate the login test failure")
        self.assertNotEqual(title_a, title_b)

        session_a = db_module.get_runtime_session("session-a")
        session_b = db_module.get_runtime_session("session-b")
        self.assertEqual(session_a["session_id"], "session-a")
        self.assertEqual(session_b["session_id"], "session-b")


if __name__ == "__main__":
    unittest.main()
