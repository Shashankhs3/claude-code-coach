"""Tests for the Phase 2 VS Code integration service (claude_code_coach/service/).

Follows the same TempDbTestCase isolation pattern as tests/test_runtime.py:
every test gets its own throwaway SQLite file so nothing here touches the
real user's ~/.claude_code_coach.
"""

import json
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.database import db as db_module
from claude_code_coach.service import coach_service, lifecycle, models
from claude_code_coach.service.server import safe_query_param


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
    """Starts a real service on an ephemeral port for each test."""

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
        """Returns (status_code, parsed_json_or_None)."""
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
        """Returns (status_code, parsed_json_or_None). `payload` may be a
        dict (JSON-encoded normally) or raw bytes (sent verbatim, for
        malformed-body tests)."""
        if token == "__default__":
            token = self.token
        data = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, method="POST",
        )
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


class TestServerStartupShutdown(RunningServiceTestCase):
    def test_service_reports_running_after_start(self):
        self.assertTrue(lifecycle.is_running())
        self.assertIsNotNone(self.port)

    def test_service_json_written_on_start(self):
        path = db_module.DB_PATH.parent / "service.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(data["port"], self.port)
        self.assertEqual(data["api_version"], "v1")
        self.assertIn("pid", data)
        self.assertIn("started_at", data)

    def test_second_start_call_is_a_noop_while_running(self):
        # start_service() must be idempotent-safe: calling it again while
        # already running must not raise or rebind.
        self.assertTrue(lifecycle.start_service(port=0))
        self.assertEqual(lifecycle.current_port(), self.port)

    def test_stop_removes_service_json_and_frees_port(self):
        path = db_module.DB_PATH.parent / "service.json"
        lifecycle.stop_service()
        self.assertFalse(lifecycle.is_running())
        self.assertIsNone(lifecycle.current_port())
        self.assertFalse(path.exists())
        # restart in tearDown-safe way: start again so tearDown's stop_service is a noop
        lifecycle.start_service(port=0)
        self.port = lifecycle.current_port()

    def test_start_service_never_raises_on_bind_failure(self):
        # start_service() must swallow a bind failure (return False) rather
        # than raising into app.py's startup path. Socket-level SO_REUSEADDR
        # behavior differs by platform (Windows in particular can silently
        # allow a second bind to the same port), so this exercises the
        # try/except in lifecycle.start_service directly via monkeypatching
        # the server class, rather than relying on real port contention.
        from claude_code_coach.service import lifecycle as lifecycle_module

        def _raise(*args, **kwargs):
            raise OSError("port in use (simulated)")

        original_cls = lifecycle_module.CoachHTTPServer
        lifecycle_module.CoachHTTPServer = _raise
        try:
            # The already-running instance from setUp() must be left alone:
            # start_service() returns True immediately for an already-running
            # handle, without ever reaching the (patched) constructor.
            self.assertTrue(lifecycle_module.start_service(port=0))
            lifecycle_module.stop_service()
            result = lifecycle_module.start_service(port=0)
            self.assertFalse(result)
            self.assertFalse(lifecycle_module.is_running())
        finally:
            lifecycle_module.CoachHTTPServer = original_cls
            lifecycle_module.start_service(port=0)
            self.port = lifecycle_module.current_port()


class TestHealthEndpoint(RunningServiceTestCase):
    def test_health_returns_ready_without_touching_database(self):
        status, body = self.call("/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["api_version"], "v1")
        self.assertEqual(body["service"], "claude-code-coach")

    def test_health_does_not_require_recent_activity(self):
        # No sessions exist at all yet — health must still be 200.
        status, body = self.call("/api/v1/health")
        self.assertEqual(status, 200)


class TestAuthAndValidation(RunningServiceTestCase):
    def test_missing_token_is_unauthorized(self):
        status, body = self.call("/api/v1/health", token=None)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "unauthorized")

    def test_wrong_token_is_unauthorized(self):
        status, body = self.call("/api/v1/health", token="not-the-real-token")
        self.assertEqual(status, 401)

    def test_unknown_path_is_404(self):
        status, body = self.call("/api/v1/does-not-exist")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "not_found")

    def test_post_is_method_not_allowed(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/v1/health", method="POST", data=b"{}",
        )
        req.add_header("X-Coach-Token", self.token)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 405)

    def test_oversized_query_param_is_rejected_not_crashed(self):
        long_value = "a" * 5000
        status, body = self.call("/api/v1/session?cwd=" + long_value)
        # safe_query_param() drops params over MAX_PARAM_LENGTH -> cwd becomes
        # None -> falls back to default project root, never a 500.
        self.assertEqual(status, 200)

    def test_control_characters_in_query_param_are_rejected(self):
        bad = urllib.parse.quote("a\x00b\x01c")
        status, body = self.call(f"/api/v1/session?cwd={bad}")
        self.assertEqual(status, 200)  # rejected internally, not a crash

    def test_malformed_percent_encoding_does_not_crash_server(self):
        status, body = self.call("/api/v1/session?cwd=%zz%zz")
        self.assertIn(status, (200, 400, 500))
        # Whatever the status, the server must still be alive afterward:
        status2, _ = self.call("/api/v1/health")
        self.assertEqual(status2, 200)


class TestSafeQueryParam(unittest.TestCase):
    def test_none_when_absent(self):
        self.assertIsNone(safe_query_param({}, "cwd"))

    def test_none_when_empty_string(self):
        self.assertIsNone(safe_query_param({"cwd": [""]}, "cwd"))

    def test_none_when_too_long(self):
        self.assertIsNone(safe_query_param({"cwd": ["a" * 5000]}, "cwd"))

    def test_none_when_contains_control_char(self):
        self.assertIsNone(safe_query_param({"cwd": ["a\x00b"]}, "cwd"))

    def test_strips_whitespace(self):
        self.assertEqual(safe_query_param({"cwd": ["  C:\\Foo  "]}, "cwd"), "C:\\Foo")


class TestProjectIdentification(RunningServiceTestCase):
    def test_environment_endpoint_returns_shape(self):
        status, body = self.call("/api/v1/environment")
        self.assertEqual(status, 200)
        for key in ("project_root", "scanned_at", "counts", "claude_md", "skills",
                    "agents", "mcp_servers", "errors"):
            self.assertIn(key, body)

    def test_status_endpoint_reflects_explicit_project_root(self):
        status, body = self.call("/api/v1/status?project_root=" + urllib.parse.quote("C:\\Projects\\Foo"))
        self.assertEqual(status, 200)
        self.assertEqual(body["project_root"], "C:\\Projects\\Foo")

    def test_session_endpoint_for_unknown_cwd_returns_null_session(self):
        status, body = self.call("/api/v1/session?cwd=" + urllib.parse.quote("C:\\Nowhere"))
        self.assertEqual(status, 200)
        self.assertIsNone(body["session"])
        self.assertEqual(body["cwd"], "C:\\Nowhere")


class TestApiVersioning(RunningServiceTestCase):
    def test_every_endpoint_reports_v1_where_applicable(self):
        status, body = self.call("/api/v1/health")
        self.assertEqual(body["api_version"], "v1")

    def test_models_api_version_constant_matches_route_prefix(self):
        self.assertEqual(models.API_VERSION, "v1")


class TestMultipleProjectRequests(RunningServiceTestCase):
    def test_two_different_cwds_yield_independent_results(self):
        # Manually seed two sessions with different cwd via the DB layer
        # directly (equivalent to two real hook-driven sessions).
        with db_module.get_connection() as conn:
            conn.execute(
                "INSERT INTO runtime_sessions (session_id, started_at, last_event_at, cwd, prompts) "
                "VALUES (?, ?, ?, ?, ?)",
                ("s-a", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "C:\\Projects\\A", 3),
            )
            conn.execute(
                "INSERT INTO runtime_sessions (session_id, started_at, last_event_at, cwd, prompts) "
                "VALUES (?, ?, ?, ?, ?)",
                ("s-b", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "C:\\Projects\\B", 7),
            )
            conn.commit()

        status_a, body_a = self.call("/api/v1/session?cwd=" + urllib.parse.quote("C:\\Projects\\A"))
        status_b, body_b = self.call("/api/v1/session?cwd=" + urllib.parse.quote("C:\\Projects\\B"))

        self.assertEqual(status_a, 200)
        self.assertEqual(status_b, 200)
        self.assertEqual(body_a["session"]["session_id"], "s-a")
        self.assertEqual(body_b["session"]["session_id"], "s-b")
        self.assertNotEqual(body_a["session"]["session_id"], body_b["session"]["session_id"])

    def test_cwd_matching_is_case_and_slash_insensitive(self):
        with db_module.get_connection() as conn:
            conn.execute(
                "INSERT INTO runtime_sessions (session_id, started_at, last_event_at, cwd) "
                "VALUES (?, ?, ?, ?)",
                ("s-c", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "C:\\Projects\\Mixed"),
            )
            conn.commit()
        status, body = self.call("/api/v1/session?cwd=" + urllib.parse.quote("c:/projects/mixed"))
        self.assertEqual(status, 200)
        self.assertEqual(body["session"]["session_id"], "s-c")


class TestServiceUnavailable(unittest.TestCase):
    def test_client_gets_connection_error_when_nothing_listening(self):
        # No service started on this port — a VS Code client must see a
        # plain connection failure it can render as "Coach Offline", not a
        # hang or a crash.
        req = urllib.request.Request("http://127.0.0.1:1/api/v1/health")
        with self.assertRaises((urllib.error.URLError, ConnectionError)):
            urllib.request.urlopen(req, timeout=2)


class TestMigrationAddsCwd(TempDbTestCase):
    def test_cwd_column_exists_on_fresh_schema(self):
        with db_module.get_connection() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(runtime_sessions)")}
        self.assertIn("cwd", cols)

    def test_migration_is_idempotent_and_preserves_existing_rows(self):
        # Simulate a pre-v6 database: drop and recreate the table without cwd,
        # insert a row, then re-run ensure_schema() and confirm the column is
        # added non-destructively.
        from claude_code_coach.database.migrations import ensure_schema

        with db_module.get_connection() as conn:
            conn.execute("DROP TABLE IF EXISTS runtime_sessions")
            conn.execute(
                "CREATE TABLE runtime_sessions (session_id TEXT PRIMARY KEY, "
                "started_at TEXT, last_event_at TEXT)"
            )
            conn.execute(
                "INSERT INTO runtime_sessions (session_id, started_at, last_event_at) "
                "VALUES ('pre-v6', '2025-01-01T00:00:00', '2025-01-01T00:00:00')"
            )
            conn.commit()
            ensure_schema(conn)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(runtime_sessions)")}
            self.assertIn("cwd", cols)
            row = conn.execute(
                "SELECT cwd FROM runtime_sessions WHERE session_id = 'pre-v6'"
            ).fetchone()
            self.assertEqual(row[0], "")

            # Running it again must not raise or duplicate the column.
            ensure_schema(conn)


class TestSignalCreation(TempDbTestCase):
    def test_signal_file_absent_before_any_event(self):
        signal_path = db_module.DB_PATH.parent / "vscode_signal.txt"
        self.assertFalse(signal_path.exists())

    def test_drain_with_no_events_does_not_create_signal(self):
        drained = coach_service.new_events_since_last_drain()
        self.assertEqual(drained, 0)

    def test_real_hook_event_drives_drain_and_signal_via_running_service(self):
        # End-to-end: real hook_receiver.py subprocess -> drain thread picks
        # it up -> signal file written -> session endpoint reflects it,
        # scoped correctly by cwd.
        import os

        started = lifecycle.start_service(port=0)
        self.assertTrue(started)
        try:
            port = lifecycle.current_port()
            service_json = json.loads((db_module.DB_PATH.parent / "service.json").read_text())
            token = service_json["token"]

            fake_home = Path(self._tmpdir.name) / "fake_home"
            (fake_home / ".claude_code_coach").mkdir(parents=True, exist_ok=True)

            receiver = Path("claude_code_coach/runtime/hook_receiver.py").resolve()
            env = dict(__import__("os").environ)
            env["USERPROFILE"] = str(fake_home)
            env["HOME"] = str(fake_home)

            # hook_receiver.py computes its own APP_DIR from Path.home(), so
            # for this one test the shared DB path must line up with it —
            # temporarily repoint db_module.DB_PATH there too.
            original = db_module.DB_PATH
            db_module.DB_PATH = fake_home / ".claude_code_coach" / "coach.db"
            db_module.init_db()
            try:
                lifecycle.stop_service()
                started = lifecycle.start_service(port=0)
                self.assertTrue(started)
                port = lifecycle.current_port()
                service_json = json.loads((db_module.DB_PATH.parent / "service.json").read_text())
                token = service_json["token"]

                def fire(payload):
                    r = subprocess.run(
                        [sys.executable, str(receiver)], input=json.dumps(payload),
                        capture_output=True, text=True, env=env, timeout=30,
                    )
                    self.assertEqual(r.returncode, 0, r.stderr)

                fire({"session_id": "test-signal", "hook_event_name": "SessionStart",
                      "cwd": "C:\\Projects\\SignalTest"})
                fire({"session_id": "test-signal", "hook_event_name": "UserPromptSubmit",
                      "prompt": "Add a unit test."})

                signal_path = db_module.DB_PATH.parent / "vscode_signal.txt"
                deadline = time.time() + 6
                while time.time() < deadline and not signal_path.exists():
                    time.sleep(0.2)
                self.assertTrue(signal_path.exists(), "drain loop never wrote the signal file")

                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/v1/session?cwd="
                    + urllib.parse.quote("C:\\Projects\\SignalTest")
                )
                req.add_header("X-Coach-Token", token)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    body = json.loads(resp.read())
                self.assertIsNotNone(body["session"])
                self.assertEqual(body["session"]["session_id"], "test-signal")
                self.assertEqual(body["session"]["prompts"], 1)

                req2 = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/v1/session?cwd="
                    + urllib.parse.quote("C:\\Projects\\SomeOtherProject")
                )
                req2.add_header("X-Coach-Token", token)
                with urllib.request.urlopen(req2, timeout=5) as resp:
                    body2 = json.loads(resp.read())
                self.assertIsNone(body2["session"])
            finally:
                db_module.DB_PATH = original
        finally:
            lifecycle.stop_service()


class TestAnalyzeEndpoint(RunningServiceTestCase):
    def test_valid_prompt_returns_real_analysis(self):
        status, body = self.post("/api/v1/analyze", {"prompt": "fix it"})
        self.assertEqual(status, 200)
        self.assertEqual(body["prompt"], "fix it")
        self.assertIn("score", body)
        self.assertIn("rating", body)
        self.assertIn("dimensions", body)
        self.assertIn("goal", body["dimensions"])

    def test_missing_prompt_is_400(self):
        status, body = self.post("/api/v1/analyze", {})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_request")

    def test_non_string_prompt_is_400(self):
        status, body = self.post("/api/v1/analyze", {"prompt": 123})
        self.assertEqual(status, 400)

    def test_empty_string_prompt_is_400(self):
        status, body = self.post("/api/v1/analyze", {"prompt": "   "})
        self.assertEqual(status, 400)

    def test_oversized_prompt_is_400_not_crash(self):
        status, body = self.post("/api/v1/analyze", {"prompt": "a" * 30_000})
        self.assertEqual(status, 400)
        status2, _ = self.call("/api/v1/health")
        self.assertEqual(status2, 200)  # server must still be alive

    def test_malformed_json_body_is_400(self):
        status, body = self.post("/api/v1/analyze", b"{not valid json")
        self.assertEqual(status, 400)

    def test_non_object_json_body_is_400(self):
        status, body = self.post("/api/v1/analyze", b'"just a string"')
        self.assertEqual(status, 400)

    def test_missing_content_length_is_411(self):
        conn = __import__("http.client", fromlist=["client"]).HTTPConnection(
            "127.0.0.1", self.port
        )
        conn.putrequest("POST", "/api/v1/analyze")
        conn.putheader("X-Coach-Token", self.token)
        conn.endheaders()  # no Content-Length, no body
        resp = conn.getresponse()
        self.assertEqual(resp.status, 411)
        conn.close()

    def test_body_too_large_is_413(self):
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        oversized = b'{"prompt": "' + b"a" * 100_000 + b'"}'
        conn.request(
            "POST", "/api/v1/analyze", body=oversized,
            headers={"X-Coach-Token": self.token, "Content-Length": str(len(oversized))},
        )
        resp = conn.getresponse()
        self.assertEqual(resp.status, 413)
        conn.close()

    def test_missing_token_is_401(self):
        status, body = self.post("/api/v1/analyze", {"prompt": "fix it"}, token=None)
        self.assertEqual(status, 401)

    def test_unknown_post_route_is_404(self):
        status, body = self.post("/api/v1/nope", {"prompt": "x"})
        self.assertEqual(status, 404)

    def test_post_to_get_only_route_is_405(self):
        status, body = self.post("/api/v1/health", {})
        self.assertEqual(status, 405)


class TestSuggestEndpoint(RunningServiceTestCase):
    def test_underspecified_prompt_returns_a_rewrite(self):
        status, body = self.post("/api/v1/suggest", {"prompt": "fix it"})
        self.assertEqual(status, 200)
        self.assertIn("category", body)
        self.assertIn("message", body)
        self.assertIn("suggested_text", body)

    def test_good_prompt_may_have_no_safe_rewrite(self):
        # A well-specified prompt should never get a fabricated "improvement"
        # -- suggested_text may legitimately be None.
        good_prompt = (
            "Fix the null pointer exception in src/auth/login.py's "
            "validate_token function. Do not change the public API. "
            "Done when the existing test suite passes."
        )
        status, body = self.post("/api/v1/suggest", {"prompt": good_prompt})
        self.assertEqual(status, 200)
        self.assertIn("suggested_text", body)  # key present even if null

    def test_missing_prompt_is_400(self):
        status, body = self.post("/api/v1/suggest", {})
        self.assertEqual(status, 400)


class TestApproachEndpoint(RunningServiceTestCase):
    def test_valid_prompt_returns_recommendations(self):
        status, body = self.post("/api/v1/approach", {"prompt": "Investigate the failing test."})
        self.assertEqual(status, 200)
        self.assertIn("recommendations", body)
        self.assertIsInstance(body["recommendations"], list)
        self.assertGreaterEqual(len(body["recommendations"]), 1)  # always at least normal_session

    def test_missing_prompt_is_400(self):
        status, body = self.post("/api/v1/approach", {})
        self.assertEqual(status, 400)

    def test_recommendation_preserves_real_confidence_levels(self):
        status, body = self.post("/api/v1/approach", {"prompt": "Do something."})
        self.assertEqual(status, 200)
        for rec in body["recommendations"]:
            self.assertIn(rec["level"], ("low", "medium", "high"))
            self.assertIn("kind", rec)
            self.assertIn("evidence", rec)

    def test_invalid_project_root_type_is_400(self):
        status, body = self.post(
            "/api/v1/approach", {"prompt": "x", "project_root": 123},
        )
        self.assertEqual(status, 400)

    def test_invalid_cwd_type_is_400(self):
        status, body = self.post("/api/v1/approach", {"prompt": "x", "cwd": 123})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
