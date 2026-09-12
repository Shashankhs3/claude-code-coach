"""Loopback-only HTTP server for the VS Code integration (Phase 2/3).

Binds `127.0.0.1` ONLY — never `0.0.0.0`. Every request must carry a
matching `X-Coach-Token` header (written to `service.json` at startup, a
file with the same OS-account-level access `coach.db` already has).
Nothing in a query string or POST body is ever passed to a shell or
`exec`/`eval` — only to `analyzer.analyze_prompt`/`suggest_prompt`/
`recommend_approach` (pure, deterministic functions) or a `Path(...)`/
sqlite query, exactly like every other local path/prompt the desktop UI
already accepts from the user.

Phase 3 adds POST for exactly three routes (analyze/suggest/approach) —
these carry a prompt in the body (too long/free-form for a query string),
but remain pure analysis calls: nothing is written to disk or the
database by any of them. GET-only routes are unchanged.
"""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import coach_service

MAX_PARAM_LENGTH = 4096
# Bounds the POST body itself (JSON overhead + prompt + optional
# project_root/cwd) — coach_service.MAX_PROMPT_LENGTH bounds the prompt
# field specifically; this bounds the raw bytes read off the socket
# before any JSON parsing happens at all.
MAX_BODY_LENGTH = 65_536

logger = logging.getLogger("claude_code_coach.service")


def safe_query_param(qs: dict, name: str) -> str | None:
    """Bounded, control-character-free extraction — never crashes a handler
    thread on a malformed/oversized/binary query value.
    """
    values = qs.get(name)
    if not values:
        return None
    value = values[0]
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > MAX_PARAM_LENGTH:
        return None
    if any(ord(c) < 0x20 for c in value):
        return None
    return value


# Route table: path -> callable(query_dict) -> JSON-safe dict.
# Every handler here is a one-line call into service/coach_service.py —
# the HTTP layer intentionally contains no analysis logic of its own.
ROUTES = {
    "/api/v1/health": lambda qs: coach_service.health(),
    "/api/v1/status": lambda qs: coach_service.status(
        project_root=safe_query_param(qs, "project_root"),
    ),
    "/api/v1/session": lambda qs: coach_service.session(
        cwd=safe_query_param(qs, "cwd"),
        project_root=safe_query_param(qs, "project_root"),
    ),
    "/api/v1/environment": lambda qs: coach_service.environment(
        project_root=safe_query_param(qs, "project_root"),
    ),
}

# Phase 3: POST route table -> callable(payload_dict) -> JSON-safe dict.
# Same one-line-into-coach_service discipline as ROUTES above.
# Phase 4E adds /api/v1/pause: the one shared, mutable piece of coaching
# state a client with no direct coach.db access (VS Code) needs to change
# remotely — not destructive, just a preference toggle (docs/
# SHARED_COACH_STATE.md §14).
POST_ROUTES = {
    "/api/v1/analyze": coach_service.analyze,
    "/api/v1/suggest": coach_service.suggest,
    "/api/v1/approach": coach_service.approach,
    "/api/v1/pause": coach_service.set_paused,
}


class CoachHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler_cls, *, token: str):
        super().__init__(server_address, handler_cls)
        self.token = token


class CoachRequestHandler(BaseHTTPRequestHandler):
    server: CoachHTTPServer  # type: ignore[assignment]
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A002 - stdlib signature
        # Deliberately generic: method/path/status only. A future endpoint
        # that accepts prompt text must never route it through here.
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _write_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client disconnected mid-response — not our problem to raise on

    def _token_ok(self) -> bool:
        expected = self.server.token
        got = self.headers.get("X-Coach-Token", "")
        return bool(expected) and got == expected

    def do_GET(self) -> None:  # noqa: N802 - stdlib method name
        parsed = urlparse(self.path)
        route = ROUTES.get(parsed.path)

        if route is None:
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found", "path": parsed.path})
            return

        if not self._token_ok():
            self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        qs = parse_qs(parsed.query, keep_blank_values=False)
        try:
            result = route(qs)
        except Exception:  # noqa: BLE001 - a bad/edge-case request must never crash the server thread
            logger.exception("handler error for %s", parsed.path)
            self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal_error"})
            return

        self._write_json(HTTPStatus.OK, result)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = POST_ROUTES.get(parsed.path)

        if route is None:
            # Covers both "not a route at all" and "a GET-only route hit
            # with POST" — either way, method_not_allowed is the honest
            # answer for a known GET route, not_found for an unknown path.
            status = (
                HTTPStatus.METHOD_NOT_ALLOWED if parsed.path in ROUTES else HTTPStatus.NOT_FOUND
            )
            error = "method_not_allowed" if status == HTTPStatus.METHOD_NOT_ALLOWED else "not_found"
            self._write_json(status, {"error": error})
            return

        if not self._token_ok():
            self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        payload = self._read_json_body()
        if payload is None:
            return  # _read_json_body already wrote the error response

        try:
            result = route(payload)
        except coach_service.InvalidRequestError as exc:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "detail": str(exc)})
            return
        except Exception:  # noqa: BLE001 - a bad/edge-case request must never crash the server thread
            logger.exception("handler error for %s", parsed.path)
            self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal_error"})
            return

        self._write_json(HTTPStatus.OK, result)

    def _read_json_body(self) -> dict | None:
        """Reads and parses a bounded JSON request body. Writes an error
        response and returns None on any problem — never raises, never
        logs the body itself (it may contain prompt text)."""
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            self._write_json(HTTPStatus.LENGTH_REQUIRED, {"error": "content_length_required"})
            return None
        try:
            length = int(length_header)
        except ValueError:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"})
            return None
        if length < 0 or length > MAX_BODY_LENGTH:
            self._write_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body_too_large"})
            return None

        try:
            raw = self.rfile.read(length)
        except OSError:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "body_read_failed"})
            return None

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return None

        if not isinstance(payload, dict):
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "detail": "body must be a JSON object"})
            return None

        return payload
