"""Application bootstrap: QApplication + MainWindow, offline and local-only."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from claude_code_coach.database import init_db
from claude_code_coach.service import start_service, stop_service
from claude_code_coach.ui import MainWindow
from claude_code_coach.ui.theme import STYLESHEET


def run() -> int:
    init_db()

    app = QApplication(sys.argv)
    app.setApplicationName("Claude Code Coach")
    app.setStyleSheet(STYLESHEET)

    window = MainWindow()
    window.show()

    if window.controller.scan_on_startup:
        window.controller.scan_environment_async(on_done=lambda snap: window.controller.refresh_all())

    # VS Code integration (Phase 2): loopback-only, starts/stops with this
    # process. A failed bind (e.g. port in use) never affects the app
    # itself — see service/lifecycle.py.
    start_service()
    app.aboutToQuit.connect(stop_service)
    # Give any in-flight background scan (environment or usage) a bounded
    # chance to actually stop before Qt tears down its QThread — see
    # CoachController.shutdown()'s docstring for the real bug this closes.
    app.aboutToQuit.connect(window.controller.shutdown)

    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
