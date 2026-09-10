"""Loopback-only HTTP server for the VS Code integration (Phase 2).

Binds `127.0.0.1` ONLY — never `0.0.0.0`. Every request must carry a
matching `X-Coach-Token` header (written to `service.json` at startup, a
file with the same OS-account-level access `coach.db` already has). Every
route here is read-only: no request body is ever accepted, nothing in a
query string is ever passed to a shell or `exec`/`eval` — only to a
`Path(...)`/sqlite query, exactly like every other local path the desktop
UI already accepts from the user (e.g. "Choose Project Folder").
"""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import coach_service

MAX_PARAM_LENGTH = 4096

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
        # No mutating endpoints in Phase 2 (see architecture doc §6) — every
        # route is GET-only.
        self._write_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed"})
