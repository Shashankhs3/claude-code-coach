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
import sys
import threading
from datetime import datetime
from pathlib import Path

from .. import __version__ as _package_version
from ..database import db
from . import coach_service, models
from .server import CoachHTTPServer, CoachRequestHandler

logger = logging.getLogger("claude_code_coach.service")

DEFAULT_PORT = 47823
DRAIN_INTERVAL_SECONDS = 2.0
# Bumped only if service.json's shape changes in a way a reader must branch
# on (field removed/repurposed) — adding a field, as this phase does, is
# backward compatible and does not require a bump.
DISCOVERY_SCHEMA_VERSION = 1


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

    # Phase 4D-A: service.json is one shared file, not per-process — if an
    # external service has already overwritten it with its OWN pid/port/
    # token since we last wrote it (the exact moment a Desktop-owned
    # embedded copy hands off to a newly-appeared standalone service, see
    # CoachController's handoff check), unconditionally unlinking here
    # would delete THAT service's discovery file seconds after confirming
    # it works — the opposite of what stopping our own copy should do.
    # Only remove the file if it still names this process's own PID.
    _remove_discovery_file_if_owned_by_this_process()
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
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "service_version": _package_version,
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


def _remove_discovery_file_if_owned_by_this_process() -> None:
    """Phase 4D-A: the ownership-safe variant stop_service() actually
    uses. A missing/unreadable/malformed file is treated as "nothing of
    ours to remove" (not an error) — same tolerant read as
    read_discovery_file(), duplicated narrowly here rather than reused
    directly because this check must NOT apply read_discovery_file()'s own
    liveness/api_version filtering (a file that fails those checks for
    some OTHER reason could still be ours and still deserve cleanup)."""
    try:
        raw = _service_json_path().read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, ValueError):
        return
    if isinstance(payload, dict) and payload.get("pid") == os.getpid():
        _remove_discovery_file()


def pid_is_alive(pid: int) -> bool:
    """Stdlib-only, cross-platform "is this PID a live process" check (Phase
    4 Step 4 — a reader of service.json must never trust a stale PID
    blindly). No new dependency: ctypes on Windows (os.kill(pid, 0) is not
    a liveness check there — see below), signal 0 via os.kill on POSIX.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid,
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just owned by another user — still "alive"
    except OSError:
        return False
    return True


# Phase 4C: set by read_discovery_file() on its most recent call — same
# "last diagnostic" pattern as vscode-extension/src/coachClient.ts's
# getLastDiscoveryIssue(), so a Python caller (the desktop client, Step 3)
# can show *why* the service looks unusable instead of a single generic
# "unavailable". Reusing the exact same three checks (shape, PID liveness,
# api_version) as the TypeScript reader — see Step 3's "reuse the same
# service-discovery principles already used by VS Code" — not a second
# discovery mechanism, just this process's own reader of the one file.
_last_discovery_issue: str | None = None


def get_last_discovery_issue() -> str | None:
    return _last_discovery_issue


def read_discovery_file() -> dict | None:
    """Reads service.json and returns it only if it looks live and speaks
    an API version this process understands — returns None for "file
    missing", "file present but its PID is dead" (Step 4's stale-discovery
    requirement), and "file present but api_version is incompatible" alike,
    so every caller gets one honest signal instead of re-implementing the
    staleness/compatibility check itself. get_last_discovery_issue()
    distinguishes the three after the fact for a caller that wants to say
    more than "unavailable".
    """
    global _last_discovery_issue
    try:
        raw = _service_json_path().read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, ValueError):
        _last_discovery_issue = None  # routine: no service has ever run, or none is running
        return None
    if not isinstance(payload, dict):
        _last_discovery_issue = None
        return None
    pid = payload.get("pid")
    if not isinstance(pid, int) or not pid_is_alive(pid):
        _last_discovery_issue = (
            "Coach service discovery file is stale (the process that wrote it is no longer running)."
        )
        return None
    api_version = payload.get("api_version")
    if api_version != models.API_VERSION:
        _last_discovery_issue = (
            f"Coach service version is incompatible (service reports api_version "
            f'"{api_version}", this client supports "{models.API_VERSION}").'
        )
        return None
    _last_discovery_issue = None
    return payload


def _write_signal(reason: str, count: int) -> None:
    line = f"{reason} {datetime.now().isoformat(timespec='seconds')} {count}"
    try:
        _signal_file_path().write_text(line, encoding="utf-8")
    except OSError:
        pass


def notify_state_changed(reason: str = "state_changed") -> None:
    """Phase 4E (docs/SHARED_COACH_STATE.md §11): the one small public hook
    onto the *existing* vscode_signal.txt mechanism — reusing `_write_signal`
    rather than adding a second push system, per Step 11. A pure filesystem
    write to a shared path; safe to call from any process regardless of
    whether that process itself is running the HTTP service (e.g. Desktop
    calling this after a direct coach.db pause-flag write while a separate
    standalone service process owns the actual `_drain_loop`/httpd)."""
    _write_signal(reason, 0)


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
