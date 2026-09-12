"""Tests for Phase 4C: the desktop's Coach backend client
(claude_code_coach/service/client.py) and the single-runtime-owner rule
(CoachController.poll_runtime()).

Phase 4D-A adds: explicit BackendMode transitions, and the embedded-to-
standalone handoff (CoachController._check_for_standalone_handoff()).

Follows the same TempDbTestCase isolation pattern as
tests/test_service.py / tests/test_service_standalone.py — every test gets
its own throwaway SQLite file/home dir so nothing here touches the real
user's ~/.claude_code_coach.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.database import db as db_module
from claude_code_coach.service import BackendMode, lifecycle
from claude_code_coach.service.client import (
    CoachBackendClient,
    InvalidRequestError,
    ServiceUnavailableError,
)


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


class TestDiscoveryMissingOrMalformed(TempDbTestCase):
    def test_is_available_false_and_health_raises_when_nothing_running(self):
        client = CoachBackendClient()
        self.assertFalse(client.is_available())
        with self.assertRaises(ServiceUnavailableError):
            client.health()

    def test_is_available_false_on_malformed_json(self):
        (db_module.DB_PATH.parent / "service.json").write_text("{not valid json", encoding="utf-8")
        client = CoachBackendClient()
        self.assertFalse(client.is_available())

    def test_is_available_false_when_service_json_is_not_an_object(self):
        (db_module.DB_PATH.parent / "service.json").write_text("[1, 2, 3]", encoding="utf-8")
        client = CoachBackendClient()
        self.assertFalse(client.is_available())


class TestDiscoveryStalenessAndVersion(TempDbTestCase):
    def test_stale_pid_is_rejected_with_a_specific_diagnostic(self):
        payload = {
            "schema_version": 1, "service_version": "0.0.0", "port": 47823,
            "token": "fake", "pid": -1, "started_at": "2020-01-01T00:00:00",
            "api_version": "v1",
        }
        (db_module.DB_PATH.parent / "service.json").write_text(json.dumps(payload), encoding="utf-8")
        client = CoachBackendClient()
        self.assertFalse(client.is_available())
        self.assertIn("stale", (client.discovery_issue() or "").lower())

    def test_incompatible_api_version_is_rejected_with_a_specific_diagnostic(self):
        payload = {
            "schema_version": 1, "service_version": "9.9.9", "port": 47823,
            "token": "fake", "pid": os.getpid(), "started_at": "2020-01-01T00:00:00",
            "api_version": "v2",
        }
        (db_module.DB_PATH.parent / "service.json").write_text(json.dumps(payload), encoding="utf-8")
        client = CoachBackendClient()
        self.assertFalse(client.is_available())
        issue = client.discovery_issue() or ""
        self.assertIn("incompatible", issue.lower())
        self.assertIn("v2", issue)

    def test_live_pid_and_matching_api_version_is_accepted(self):
        payload = {
            "schema_version": 1, "service_version": "3.0.0", "port": 47823,
            "token": "fake", "pid": os.getpid(), "started_at": "2020-01-01T00:00:00",
            "api_version": "v1",
        }
        (db_module.DB_PATH.parent / "service.json").write_text(json.dumps(payload), encoding="utf-8")
        client = CoachBackendClient()
        self.assertTrue(client.is_available())
        self.assertIsNone(client.discovery_issue())


class TestClientAgainstARealRunningService(TempDbTestCase):
    def setUp(self):
        super().setUp()
        started = lifecycle.start_service(port=0)
        self.assertTrue(started, "service failed to bind an ephemeral port")
        self.client = CoachBackendClient()

    def test_health_status_session_environment_all_succeed(self):
        self.assertTrue(self.client.is_available())
        health = self.client.health()
        self.assertEqual(health["status"], "ready")

        status = self.client.status()
        self.assertIn("connected", status)

        session = self.client.session(cwd="C:\\Projects\\Demo")
        self.assertIn("session", session)

        environment = self.client.environment()
        self.assertIn("skills", environment)

    def test_analyze_suggest_approach_round_trip(self):
        analysis = self.client.analyze("fix it")
        self.assertEqual(analysis["prompt"], "fix it")

        suggestion = self.client.suggest("fix it")
        self.assertIn("suggested_text", suggestion)

        approach = self.client.approach("Investigate the bug.", project_root="C:\\Demo")
        self.assertIsInstance(approach["recommendations"], list)

    def test_empty_prompt_raises_invalid_request_error_not_service_unavailable(self):
        with self.assertRaises(InvalidRequestError):
            self.client.analyze("")

    def test_wrong_token_is_reported_as_service_unavailable(self):
        # Simulate a corrupted/tampered discovery file (wrong token) rather
        # than a missing one — must fail the same clean way, never a raw
        # exception leaking past this layer.
        service_json_path = db_module.DB_PATH.parent / "service.json"
        payload = json.loads(service_json_path.read_text())
        payload["token"] = "wrong-token"
        service_json_path.write_text(json.dumps(payload), encoding="utf-8")
        client = CoachBackendClient()
        with self.assertRaises(ServiceUnavailableError):
            client.health()


class TestReconnection(TempDbTestCase):
    def test_client_recovers_automatically_once_service_restarts(self):
        client = CoachBackendClient()
        self.assertFalse(client.is_available())

        started = lifecycle.start_service(port=0)
        self.assertTrue(started)
        try:
            # Same client instance, no re-construction needed — every call
            # re-reads service.json fresh (Step 19: never permanently cache
            # port/token/PID).
            self.assertTrue(client.is_available())
            self.assertEqual(client.health()["status"], "ready")
        finally:
            lifecycle.stop_service()

        self.assertFalse(client.is_available())

        # "Service restarts" (Scenario E): a new process, new port/token.
        started_again = lifecycle.start_service(port=0)
        self.assertTrue(started_again)
        self.assertTrue(client.is_available())
        self.assertEqual(client.health()["status"], "ready")


class TestRuntimeOwnership(TempDbTestCase):
    """Step 8/23: prove the Desktop does not drain runtime_events/*.jsonl
    itself while a Coach service already owns that job."""

    def _make_controller(self):
        from claude_code_coach.ui.controller import CoachController
        return CoachController()

    def test_poll_runtime_drains_locally_when_no_service_is_reachable(self):
        controller = self._make_controller()
        self.assertFalse(controller.has_reachable_backend())
        with mock.patch.object(
            controller.runtime_coach, "poll_and_store", return_value=0,
        ) as mocked_poll:
            controller.poll_runtime()
        mocked_poll.assert_called_once()

    def test_poll_runtime_skips_local_drain_when_a_service_is_reachable(self):
        controller = self._make_controller()
        started = lifecycle.start_service(port=0)
        self.assertTrue(started)
        try:
            self.assertTrue(controller.has_reachable_backend())
            with mock.patch.object(
                controller.runtime_coach, "poll_and_store", return_value=0,
            ) as mocked_poll:
                result = controller.poll_runtime()
            mocked_poll.assert_not_called()
            self.assertEqual(result, 0)
        finally:
            lifecycle.stop_service()

    def test_poll_runtime_resumes_local_drain_once_the_service_disappears(self):
        # Step 18: reconnect/disconnect must never require restarting the
        # Desktop — the very next poll_runtime() call must reflect the
        # current reality, not a value cached at controller construction.
        controller = self._make_controller()
        started = lifecycle.start_service(port=0)
        self.assertTrue(started)
        self.assertTrue(controller.has_reachable_backend())
        lifecycle.stop_service()
        self.assertFalse(controller.has_reachable_backend())
        with mock.patch.object(
            controller.runtime_coach, "poll_and_store", return_value=0,
        ) as mocked_poll:
            controller.poll_runtime()
        mocked_poll.assert_called_once()

    def test_coach_backend_summary_reports_unreachable_when_nothing_running(self):
        controller = self._make_controller()
        summary = controller.coach_backend_summary()
        self.assertFalse(summary["reachable"])
        self.assertFalse(summary["using_standalone"])

    def test_coach_backend_summary_distinguishes_own_embedded_service_from_external_one(self):
        controller = self._make_controller()

        # This controller's own process starts the service (mirrors what
        # app.py does when it is the one to call start_service()).
        started = lifecycle.start_service(port=0)
        self.assertTrue(started)
        try:
            summary = controller.coach_backend_summary()
            self.assertTrue(summary["reachable"])
            self.assertFalse(summary["using_standalone"], "this process's own embedded copy is not 'standalone'")
        finally:
            lifecycle.stop_service()


class TestBackendModeTransitions(TempDbTestCase):
    """Phase 4D-A Step 2/14: the three explicit states."""

    def _make_controller(self):
        from claude_code_coach.ui.controller import CoachController
        return CoachController()

    def test_unavailable_when_nothing_is_running(self):
        controller = self._make_controller()
        self.assertEqual(controller.current_backend_mode(), BackendMode.UNAVAILABLE)

    def test_embedded_fallback_when_this_process_owns_the_service(self):
        controller = self._make_controller()
        started = lifecycle.start_service(port=0)
        self.assertTrue(started)
        try:
            self.assertEqual(controller.current_backend_mode(), BackendMode.EMBEDDED_FALLBACK)
        finally:
            lifecycle.stop_service()

    def test_standalone_when_an_external_alive_process_owns_discovery(self):
        # A real, alive, different PID — but not actually serving HTTP —
        # is sufficient for STANDALONE mode: current_backend_mode() only
        # needs discovery to look valid (see BackendClient.is_available()),
        # not a successful request. The handoff check (below) is what
        # additionally requires a real health() response.
        helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            payload = {
                "schema_version": 1, "service_version": "9.9.9", "port": 1,
                "token": "fake", "pid": helper.pid, "started_at": "2020-01-01T00:00:00",
                "api_version": "v1",
            }
            (db_module.DB_PATH.parent / "service.json").write_text(json.dumps(payload), encoding="utf-8")
            controller = self._make_controller()
            self.assertEqual(controller.current_backend_mode(), BackendMode.STANDALONE)
        finally:
            helper.terminate()
            helper.wait(timeout=10)


class TestEmbeddedToStandaloneHandoff(unittest.TestCase):
    """Phase 4D-A Step 3/4/8/14: the actual handoff logic, against real
    processes — not mocks — since the whole point is proving the ownership
    transition is real (service.json ends up naming the standalone
    process, this process's own embedded copy is genuinely stopped)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_path = db_module.DB_PATH
        self.fake_home = Path(self._tmpdir.name) / "fake_home"
        (self.fake_home / ".claude_code_coach").mkdir(parents=True, exist_ok=True)
        db_module.DB_PATH = self.fake_home / ".claude_code_coach" / "test_coach.db"
        db_module.init_db()
        self._standalone_proc: subprocess.Popen | None = None

    def tearDown(self):
        if self._standalone_proc is not None:
            self._standalone_proc.terminate()
            try:
                self._standalone_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._standalone_proc.kill()
                self._standalone_proc.wait(timeout=10)
        if lifecycle.is_running():
            lifecycle.stop_service()
        db_module.DB_PATH = self._original_path
        self._tmpdir.cleanup()

    def _make_controller(self):
        from claude_code_coach.ui.controller import CoachController
        return CoachController()

    def _spawn_real_standalone_service(self) -> int:
        env = dict(os.environ)
        env["USERPROFILE"] = str(self.fake_home)
        env["HOME"] = str(self.fake_home)
        self._standalone_proc = subprocess.Popen(
            [sys.executable, "-m", "claude_code_coach.service", "--port", "0"],
            cwd=str(Path(__file__).resolve().parent.parent),
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        # Poll for a pid OTHER than this test process's own — this
        # directory's service.json may already exist (this process's own
        # embedded copy, started earlier in the same test), so "the file
        # exists" alone is not sufficient; wait for the subprocess to
        # actually overwrite it with its own pid.
        service_json_path = self.fake_home / ".claude_code_coach" / "service.json"
        deadline = time.time() + 10
        while time.time() < deadline:
            if service_json_path.exists():
                try:
                    pid = json.loads(service_json_path.read_text())["pid"]
                    if pid != os.getpid():
                        return pid
                except (ValueError, KeyError):
                    pass
            time.sleep(0.1)
        self.fail("standalone service never overwrote service.json with its own pid")

    def test_no_op_when_this_process_does_not_own_the_embedded_service(self):
        controller = self._make_controller()
        # Nothing running at all — must not raise, must not start anything.
        controller._check_for_standalone_handoff()
        self.assertEqual(controller.current_backend_mode(), BackendMode.UNAVAILABLE)

    def test_no_op_when_discovery_file_is_just_this_process_own(self):
        controller = self._make_controller()
        started = lifecycle.start_service(port=0)
        self.assertTrue(started)
        controller._check_for_standalone_handoff()
        # Still embedded — the discovery file is our own, nothing to hand off to.
        self.assertEqual(controller.current_backend_mode(), BackendMode.EMBEDDED_FALLBACK)
        self.assertTrue(lifecycle.is_running())

    def test_stays_embedded_when_candidate_pid_is_alive_but_not_answering(self):
        # Step 4's exact race: a live PID with a plausible discovery file,
        # but nothing actually listening on the claimed port.
        controller = self._make_controller()
        started = lifecycle.start_service(port=0)
        self.assertTrue(started)
        helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            payload = {
                "schema_version": 1, "service_version": "9.9.9", "port": 1,
                "token": "fake", "pid": helper.pid, "started_at": "2020-01-01T00:00:00",
                "api_version": "v1",
            }
            (db_module.DB_PATH.parent / "service.json").write_text(json.dumps(payload), encoding="utf-8")

            controller._check_for_standalone_handoff()

            # Must NOT have stopped the embedded copy over an unreachable candidate.
            self.assertTrue(lifecycle.is_running())
            self.assertEqual(controller.current_backend_mode(), BackendMode.EMBEDDED_FALLBACK)
        finally:
            helper.terminate()
            helper.wait(timeout=10)

    def test_real_handoff_to_a_genuinely_running_standalone_service(self):
        controller = self._make_controller()
        started = lifecycle.start_service(port=0)
        self.assertTrue(started)
        self.assertEqual(controller.current_backend_mode(), BackendMode.EMBEDDED_FALLBACK)

        standalone_pid = self._spawn_real_standalone_service()
        self.assertNotEqual(standalone_pid, os.getpid())

        controller._check_for_standalone_handoff()

        # Step 3: embedded copy genuinely released.
        self.assertFalse(lifecycle.is_running(), "embedded copy must be stopped after a real handoff")
        # Step 10 / the stop_service() ownership fix: the standalone's own
        # discovery file must survive our stop_service() call untouched —
        # proving VS Code (or anything else) reading it never sees a gap.
        info = lifecycle.read_discovery_file()
        self.assertIsNotNone(info, "the standalone's discovery file must still be valid after our handoff")
        self.assertEqual(info["pid"], standalone_pid)
        self.assertEqual(controller.current_backend_mode(), BackendMode.STANDALONE)

    def test_handoff_is_idempotent_once_standalone(self):
        # Calling the check again once already handed off must be a
        # harmless no-op (Step 4: never get stuck, never double-act).
        controller = self._make_controller()
        lifecycle.start_service(port=0)
        standalone_pid = self._spawn_real_standalone_service()
        controller._check_for_standalone_handoff()
        self.assertEqual(controller.current_backend_mode(), BackendMode.STANDALONE)

        controller._check_for_standalone_handoff()  # no embedded copy left to hand off from

        self.assertEqual(controller.current_backend_mode(), BackendMode.STANDALONE)
        info = lifecycle.read_discovery_file()
        self.assertEqual(info["pid"], standalone_pid)


if __name__ == "__main__":
    unittest.main()
