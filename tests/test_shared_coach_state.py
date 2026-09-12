"""Phase 4E: Shared Coach State Across Desktop + VS Code.

Covers docs/SHARED_COACH_STATE.md's ownership model: shared pause, the
backend-selected primary signal, and the new `/api/v1/pause` endpoint.
Follows the same TempDbTestCase/RunningServiceTestCase pattern as
tests/test_service.py and tests/test_desktop_client.py.
"""

import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.database import db as db_module
from claude_code_coach.runtime import runtime_coach as runtime_coach_module
from claude_code_coach.runtime.models import RuntimeSignal, RuntimeStatus
from claude_code_coach.runtime.signal_priority import pick_primary_signal
from claude_code_coach.service import coach_service, lifecycle, models


class TempDbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_path = db_module.DB_PATH
        db_module.DB_PATH = Path(self._tmpdir.name) / "test_coach.db"
        db_module.init_db()

    def tearDown(self):
        db_module.DB_PATH = self._original_path
        self._tmpdir.cleanup()


class RunningServiceTestCase(TempDbTestCase):
    def setUp(self):
        super().setUp()
        started = lifecycle.start_service(port=0)
        self.assertTrue(started, "service failed to bind an ephemeral port")
        self.port = lifecycle.current_port()
        service_json = json.loads((db_module.DB_PATH.parent / "service.json").read_text())
        self.token = service_json["token"]

    def tearDown(self):
        lifecycle.stop_service()
        super().tearDown()

    def call(self, path: str, *, token: str | None = "__default__", timeout: float = 5.0):
        if token == "__default__":
            token = self.token
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        if token is not None:
            req.add_header("X-Coach-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                return exc.code, json.loads(body)
            except json.JSONDecodeError:
                return exc.code, None

    def post(self, path: str, payload, *, token: str | None = "__default__", timeout: float = 5.0):
        if token == "__default__":
            token = self.token
        data = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if token is not None:
            req.add_header("X-Coach-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                return exc.code, json.loads(body)
            except json.JSONDecodeError:
                return exc.code, None


def _sig(kind: str, level: str) -> RuntimeSignal:
    return RuntimeSignal(kind=kind, level=level, message=f"{kind} message")


# ---------------------------------------------------------------------------
# Primary signal selection — the single deterministic selector both clients
# must key off of (docs/SHARED_COACH_STATE.md §3/4).
# ---------------------------------------------------------------------------
class TestPickPrimarySignal(unittest.TestCase):
    def test_empty_list_returns_none(self):
        self.assertIsNone(pick_primary_signal([]))

    def test_single_signal_is_primary(self):
        sig = _sig("verification_missing", "medium")
        self.assertIs(pick_primary_signal([sig]), sig)

    def test_high_beats_medium_and_low(self):
        low, medium, high = _sig("a", "low"), _sig("b", "medium"), _sig("c", "high")
        self.assertIs(pick_primary_signal([low, medium, high]), high)
        self.assertIs(pick_primary_signal([high, medium, low]), high)

    def test_medium_beats_low(self):
        low, medium = _sig("a", "low"), _sig("b", "medium")
        self.assertIs(pick_primary_signal([low, medium]), medium)

    def test_stable_first_occurrence_wins_a_tie(self):
        first_high, second_high = _sig("first", "high"), _sig("second", "high")
        self.assertIs(pick_primary_signal([first_high, second_high]), first_high)


# ---------------------------------------------------------------------------
# session_response()'s new fields — pure unit test against a hand-built
# RuntimeStatus, no DB/HTTP needed to prove the wiring.
# ---------------------------------------------------------------------------
class TestSessionResponseSharedFields(unittest.TestCase):
    def test_primary_signal_is_none_with_no_signals(self):
        status = RuntimeStatus(
            state=mock.Mock(value="live"), last_event_at=None, hooks_installed=True,
            hooks_install_path=None, current_session=None, signals=[], paused=False,
        )
        body = models.session_response(status, cwd=None)
        self.assertIsNone(body["primary_signal"])
        self.assertFalse(body["coaching_paused"])

    def test_primary_signal_matches_pick_primary_signal(self):
        low, high = _sig("a", "low"), _sig("b", "high")
        status = RuntimeStatus(
            state=mock.Mock(value="live"), last_event_at=None, hooks_installed=True,
            hooks_install_path=None, current_session=None, signals=[low, high], paused=False,
        )
        body = models.session_response(status, cwd=None)
        self.assertEqual(body["primary_signal"]["kind"], "b")
        self.assertEqual(body["primary_signal"]["level"], "high")

    def test_coaching_paused_reflects_runtime_status(self):
        status = RuntimeStatus(
            state=mock.Mock(value="live"), last_event_at=None, hooks_installed=True,
            hooks_install_path=None, current_session=None, signals=[], paused=True,
        )
        body = models.session_response(status, cwd=None)
        self.assertTrue(body["coaching_paused"])


# ---------------------------------------------------------------------------
# Shared pause: the DB-backed flag both runtime_coach (direct/Desktop path)
# and the HTTP layer (VS Code path) read/write.
# ---------------------------------------------------------------------------
class TestSharedPauseFlag(TempDbTestCase):
    def test_defaults_to_not_paused(self):
        self.assertFalse(runtime_coach_module.is_coaching_paused())

    def test_set_and_read_roundtrip(self):
        runtime_coach_module.set_coaching_paused(True)
        self.assertTrue(runtime_coach_module.is_coaching_paused())
        runtime_coach_module.set_coaching_paused(False)
        self.assertFalse(runtime_coach_module.is_coaching_paused())

    def test_runtime_status_carries_paused_flag(self):
        runtime_coach_module.set_coaching_paused(True)
        coach = runtime_coach_module.RuntimeCoach(
            source=runtime_coach_module.HookFileEventSource(Path(self._tmpdir.name) / "runtime_events")
        )
        status = coach.status()
        self.assertTrue(status.paused)

    def test_pause_never_touches_runtime_enabled_setting(self):
        # ABSOLUTE RULE: pause suppresses interventions only, never event
        # collection — a completely separate, pre-existing setting.
        db_module.set_setting("runtime_enabled", "1")
        runtime_coach_module.set_coaching_paused(True)
        self.assertEqual(db_module.get_setting("runtime_enabled", "1"), "1")

    def test_desktop_controller_write_is_visible_to_a_fresh_runtime_coach(self):
        # Simulates Desktop (CoachController) and a standalone service
        # (a fresh RuntimeCoach instance, as coach_service.py constructs
        # per-request) sharing one coach.db file with no other sync needed.
        from claude_code_coach.ui.controller import CoachController

        controller = CoachController()
        self.assertFalse(controller.coaching_paused())
        controller.set_coaching_paused(True)
        self.assertTrue(controller.coaching_paused())

        fresh_status = runtime_coach_module.RuntimeCoach(
            source=runtime_coach_module.HookFileEventSource(Path(self._tmpdir.name) / "runtime_events")
        ).status()
        self.assertTrue(fresh_status.paused)


# ---------------------------------------------------------------------------
# POST /api/v1/pause — the one shared, mutable field VS Code needs (it has
# no direct coach.db access).
# ---------------------------------------------------------------------------
class TestPauseEndpoint(RunningServiceTestCase):
    def test_session_reports_not_paused_by_default(self):
        status, body = self.call("/api/v1/session")
        self.assertEqual(status, 200)
        self.assertFalse(body["coaching_paused"])

    def test_pause_then_session_reflects_it(self):
        status, body = self.post("/api/v1/pause", {"paused": True})
        self.assertEqual(status, 200)
        self.assertTrue(body["coaching_paused"])

        status2, session_body = self.call("/api/v1/session")
        self.assertEqual(status2, 200)
        self.assertTrue(session_body["coaching_paused"])

    def test_resume_after_pause(self):
        self.post("/api/v1/pause", {"paused": True})
        status, body = self.post("/api/v1/pause", {"paused": False})
        self.assertEqual(status, 200)
        self.assertFalse(body["coaching_paused"])
        _, session_body = self.call("/api/v1/session")
        self.assertFalse(session_body["coaching_paused"])

    def test_missing_paused_field_is_400(self):
        status, body = self.post("/api/v1/pause", {})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_request")

    def test_non_boolean_paused_field_is_400(self):
        status, body = self.post("/api/v1/pause", {"paused": "yes"})
        self.assertEqual(status, 400)

    def test_missing_token_is_401(self):
        status, _ = self.post("/api/v1/pause", {"paused": True}, token=None)
        self.assertEqual(status, 401)

    def test_pause_is_global_not_scoped_by_cwd(self):
        # Deliberate scope choice (docs/SHARED_COACH_STATE.md §5) — matches
        # VS Code's pre-existing global pause design.
        self.post("/api/v1/pause", {"paused": True})
        _, a = self.call("/api/v1/session?cwd=" + urllib.parse.quote("C:\\Projects\\A"))
        _, b = self.call("/api/v1/session?cwd=" + urllib.parse.quote("C:\\Projects\\B"))
        self.assertTrue(a["coaching_paused"])
        self.assertTrue(b["coaching_paused"])

    def test_pause_change_touches_the_shared_signal_file(self):
        # Step 11: reuse the existing vscode_signal.txt mechanism rather
        # than a second push system.
        signal_path = db_module.DB_PATH.parent / "vscode_signal.txt"
        self.assertFalse(signal_path.exists())
        self.post("/api/v1/pause", {"paused": True})
        self.assertTrue(signal_path.exists())
        self.assertIn("pause_changed", signal_path.read_text())

    def test_get_request_to_pause_endpoint_is_not_found_not_a_crash(self):
        status, _ = self.call("/api/v1/pause")
        self.assertIn(status, (404, 405))
        status2, _ = self.call("/api/v1/health")
        self.assertEqual(status2, 200)


if __name__ == "__main__":
    unittest.main()
