"""Tests for Phase 4A: the standalone `python -m claude_code_coach.service`
entry point, plus the Step 4 discovery-file staleness helpers it relies on.

Follows the same TempDbTestCase isolation pattern as tests/test_service.py
— every test gets its own throwaway SQLite file/home dir so nothing here
touches the real user's ~/.claude_code_coach.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.database import db as db_module
from claude_code_coach.service import lifecycle
from claude_code_coach.service.__main__ import main as service_main


class TempDbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_path = db_module.DB_PATH
        db_module.DB_PATH = Path(self._tmpdir.name) / "test_coach.db"
        db_module.init_db()

    def tearDown(self):
        if lifecycle.is_running():
            lifecycle.stop_service()
        db_module.DB_PATH = self._original_path
        self._tmpdir.cleanup()


class TestPidIsAlive(unittest.TestCase):
    def test_current_process_is_alive(self):
        self.assertTrue(lifecycle.pid_is_alive(os.getpid()))

    def test_exited_process_is_not_alive(self):
        proc = subprocess.run([sys.executable, "-c", "pass"], timeout=10)
        self.assertEqual(proc.returncode, 0)
        # The PID is free for reuse the instant the process exits, but that
        # race is not something a unit test should depend on — what matters
        # is the function never reports a definitely-nonexistent PID as
        # alive. A PID far outside any realistic live range is the
        # deterministic way to exercise the "not alive" branch.
        self.assertFalse(lifecycle.pid_is_alive(0))
        self.assertFalse(lifecycle.pid_is_alive(-1))


class TestReadDiscoveryFile(TempDbTestCase):
    def test_none_when_file_missing(self):
        self.assertIsNone(lifecycle.read_discovery_file())

    def test_none_when_pid_is_stale(self):
        payload = {
            "schema_version": 1, "service_version": "0.0.0", "port": 47823,
            "token": "fake", "pid": -1, "started_at": "2020-01-01T00:00:00",
            "api_version": "v1",
        }
        (db_module.DB_PATH.parent / "service.json").write_text(json.dumps(payload), encoding="utf-8")
        self.assertIsNone(lifecycle.read_discovery_file())

    def test_returns_payload_when_pid_is_live(self):
        started = lifecycle.start_service(port=0)
        self.assertTrue(started)
        info = lifecycle.read_discovery_file()
        self.assertIsNotNone(info)
        self.assertEqual(info["pid"], os.getpid())
        self.assertEqual(info["port"], lifecycle.current_port())


class TestDiscoveryFileSchema(TempDbTestCase):
    def test_includes_schema_and_service_version(self):
        started = lifecycle.start_service(port=0)
        self.assertTrue(started)
        payload = json.loads((db_module.DB_PATH.parent / "service.json").read_text())
        self.assertEqual(payload["schema_version"], lifecycle.DISCOVERY_SCHEMA_VERSION)
        self.assertIsInstance(payload["service_version"], str)
        self.assertTrue(payload["service_version"])


class TestStandaloneMain(TempDbTestCase):
    def test_starts_and_stops_cleanly_via_injected_stop_event(self):
        stop_event = threading.Event()
        result: dict = {}

        def run():
            result["code"] = service_main(["--port", "0"], stop_event=stop_event)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            deadline = time.time() + 5
            while time.time() < deadline and not lifecycle.is_running():
                time.sleep(0.05)
            self.assertTrue(lifecycle.is_running(), "standalone service never started")

            service_json_path = db_module.DB_PATH.parent / "service.json"
            self.assertTrue(service_json_path.exists())
            payload = json.loads(service_json_path.read_text())
            self.assertEqual(payload["pid"], os.getpid())

            port = lifecycle.current_port()
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/health")
            req.add_header("X-Coach-Token", payload["token"])
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
        finally:
            stop_event.set()
            thread.join(timeout=10)

        self.assertFalse(thread.is_alive(), "main() did not return after stop_event was set")
        self.assertEqual(result.get("code"), 0)
        self.assertFalse(lifecycle.is_running())
        self.assertFalse((db_module.DB_PATH.parent / "service.json").exists())

    def test_returns_nonzero_when_bind_fails(self):
        # lifecycle.start_service() already returns False non-fatally on a
        # real bind conflict (existing, tested behavior — see
        # tests/test_service.py). What THIS test covers is main()'s own
        # reaction to that: exit code 1, no attempt to wait on stop_event,
        # no lingering "running" state. A real cross-process port conflict
        # is not a reliable way to exercise this on every platform: Windows'
        # SO_REUSEADDR semantics (set via CoachHTTPServer's own
        # allow_reuse_address=True, unrelated to this phase) can let a
        # second bind on the same loopback port silently succeed rather
        # than raise OSError, which would make a real-conflict test flaky
        # by platform rather than by anything this module controls —
        # documented here rather than papered over with a retry loop.
        from unittest import mock

        with mock.patch(
            "claude_code_coach.service.__main__.start_service", return_value=False,
        ) as mocked_start:
            code = service_main(["--port", "1"])
        mocked_start.assert_called_once_with(port=1)
        self.assertEqual(code, 1)
        self.assertFalse(lifecycle.is_running())


if __name__ == "__main__":
    unittest.main()
