"""Service start/stop + discovery file + the drain-and-signal loop.

The only place besides app.py that touches process-wide service state.
Neither thread here touches Qt — both are plain `threading.Thread`, safe
to run alongside (not inside) the Qt event loop. A failure to start (e.g.
the port is already in use) must never prevent the desktop app itself from
starting — VS Code integration is simply unavailable that run.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from datetime import datetime
from pathlib import Path

from ..database import db
from . import coach_service
from .server import CoachHTTPServer, CoachRequestHandler

logger = logging.getLogger("claude_code_coach.service")

DEFAULT_PORT = 47823
DRAIN_INTERVAL_SECONDS = 2.0


def _service_json_path() -> Path:
    return db.DB_PATH.parent / "service.json"


def _signal_file_path() -> Path:
    return db.DB_PATH.parent / "vscode_signal.txt"


class _ServiceHandle:
    def __init__(self) -> None:
        self.httpd: CoachHTTPServer | None = None
        self.server_thread: threading.Thread | None = None
        self.drain_thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.port: int | None = None
        self.token: str | None = None

    @property
    def running(self) -> bool:
        return self.httpd is not None


_handle = _ServiceHandle()


def start_service(port: int = DEFAULT_PORT) -> bool:
    if _handle.running:
        return True

    token = secrets.token_urlsafe(24)
    try:
        httpd = CoachHTTPServer(("127.0.0.1", port), CoachRequestHandler, token=token)
    except OSError as exc:
        logger.warning(
            "Coach service could not bind 127.0.0.1:%s (%s) — VS Code integration "
            "disabled this run; the desktop app is unaffected.", port, exc,
        )
        return False

    _handle.httpd = httpd
    _handle.token = token
    _handle.port = httpd.server_address[1]
    _handle.stop_event.clear()

    _handle.server_thread = threading.Thread(
        target=httpd.serve_forever, name="coach-http", daemon=True,
    )
    _handle.server_thread.start()

    _handle.drain_thread = threading.Thread(
        target=_drain_loop, name="coach-drain", daemon=True,
    )
    _handle.drain_thread.start()

    _write_discovery_file()
    logger.info("Coach service listening on 127.0.0.1:%s", _handle.port)
    return True


def stop_service() -> None:
    if not _handle.running:
        return

    _handle.stop_event.set()
    try:
        _handle.httpd.shutdown()
        _handle.httpd.server_close()
    except Exception:  # noqa: BLE001 - shutdown must never raise into app.py's quit path
        logger.exception("error stopping Coach service")

    if _handle.drain_thread:
        _handle.drain_thread.join(timeout=DRAIN_INTERVAL_SECONDS * 2)

    _remove_discovery_file()
    _handle.httpd = None
    _handle.server_thread = None
    _handle.drain_thread = None
    _handle.port = None
    _handle.token = None


def is_running() -> bool:
    return _handle.running


def current_port() -> int | None:
    return _handle.port


def _write_discovery_file() -> None:
    payload = {
        "port": _handle.port,
        "token": _handle.token,
        "pid": os.getpid(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "api_version": "v1",
    }
    try:
        _service_json_path().write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        logger.warning("Could not write service.json — VS Code discovery will fail this run.")


def _remove_discovery_file() -> None:
    try:
        _service_json_path().unlink(missing_ok=True)
    except OSError:
        pass


def _write_signal(reason: str, count: int) -> None:
    line = f"{reason} {datetime.now().isoformat(timespec='seconds')} {count}"
    try:
        _signal_file_path().write_text(line, encoding="utf-8")
    except OSError:
        pass


def _drain_loop() -> None:
    """Runs for the service's lifetime: keeps runtime_events/*.jsonl draining
    into SQLite even if nobody has the desktop Sessions page open (Phase 1
    Finding V5-2), and nudges the shared signal file whenever new events
    actually arrived — this is what lets the VS Code extension react
    promptly without polling the full Coach state continuously.
    """
    while not _handle.stop_event.wait(DRAIN_INTERVAL_SECONDS):
        try:
            drained = coach_service.new_events_since_last_drain()
        except Exception:  # noqa: BLE001 - one bad drain cycle must not kill the loop
            logger.exception("drain loop error")
            continue
        if drained:
            _write_signal("runtime_event", drained)
