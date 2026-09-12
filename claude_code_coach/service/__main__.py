"""Standalone Coach service entry point (Phase 4A).

    python -m claude_code_coach.service [--port PORT]

Runs the exact same HTTP service + drain loop `app.py` starts embedded in
the desktop process (`service.lifecycle.start_service`/`stop_service` —
nothing here is reimplemented, see lifecycle.py's own docstring), but as
its own OS process with zero PySide6/Qt import anywhere in the chain. This
is what lets Claude Code Coach keep observing hook events and serving VS
Code even while the desktop GUI is not running at all (the Phase 4
success criterion).

The desktop app's own embedded `start_service()` call in app.py is
UNCHANGED by this module and keeps working exactly as before — per the
Absolute Safety Rule, this is an additive second way to start the same
service, not a replacement. Running both at once on the same machine is
safe: whichever process binds `DEFAULT_PORT` first wins, and the other's
bind attempt fails non-fatally (logged, not raised) exactly as it already
does today when the port is taken by any other process.

Stopping: Ctrl+C (SIGINT) in the foreground console, or SIGTERM, both
trigger a graceful `stop_service()` (closes the HTTP server, joins the
drain thread, removes service.json). **Windows note**: `os.kill(pid,
signal.SIGTERM)` on Windows calls `TerminateProcess` directly rather than
invoking a registered Python handler — this is a platform limitation of
Windows' signal emulation, not a bug here. On Windows, Ctrl+C in the
console this process owns (or closing that console window, which the OS
also turns into a request this process can observe) is the reliable
graceful path; a future packaged/installed service (Step 16+) would use
the platform's real service-stop mechanism instead of relying on console
signals at all.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading

from ..database import init_db
from .lifecycle import DEFAULT_PORT, current_port, start_service, stop_service

logger = logging.getLogger("claude_code_coach.service")


def main(argv: list[str] | None = None, stop_event: threading.Event | None = None) -> int:
    """`stop_event` is injectable so tests can trigger a clean shutdown
    deterministically instead of depending on real OS signal delivery
    (which, per the docstring above, behaves inconsistently for SIGTERM on
    Windows) — production callers (the `if __name__` block below) never
    pass one and get a real Event wired to SIGINT/SIGTERM.
    """
    parser = argparse.ArgumentParser(
        prog="python -m claude_code_coach.service",
        description="Standalone Claude Code Coach service — runs without the desktop GUI.",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"TCP port to bind on 127.0.0.1 (default: {DEFAULT_PORT}).",
    )
    args = parser.parse_args(argv)

    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )

    init_db()

    if not start_service(port=args.port):
        logger.error(
            "Could not start Coach service on 127.0.0.1:%s — a real "
            "process is already bound there (another standalone instance, "
            "or the desktop app). This process is exiting; the "
            "already-running service is unaffected.", args.port,
        )
        return 1

    logger.info(
        "Claude Code Coach standalone service listening on 127.0.0.1:%s "
        "(pid %s). Press Ctrl+C to stop.", current_port(), os.getpid(),
    )

    stop_event = stop_event or threading.Event()

    def _handle_stop_signal(signum, _frame) -> None:  # noqa: ANN001 - stdlib signal handler signature
        logger.info("received signal %s, shutting down", signum)
        stop_event.set()

    # Registering a signal handler only works from the interpreter's main
    # thread — true for real usage (this module's own __main__ block runs
    # there) but not for tests that drive main() from a background thread
    # via an injected stop_event; skip registration rather than raise in
    # that case, since the injected stop_event is the test's actual
    # shutdown path anyway.
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):  # SIGBREAK: Windows Ctrl+Break
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _handle_stop_signal)
        except (ValueError, OSError):
            pass

    try:
        stop_event.wait()
    finally:
        stop_service()
        logger.info("Coach service stopped.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
