"""Application bootstrap: QApplication + MainWindow, offline and local-only."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from claude_code_coach.database import init_db
from claude_code_coach.service import start_service, stop_service
from claude_code_coach.ui import MainWindow
from claude_code_coach.ui.theme import STYLESHEET
from claude_code_coach.ui.widgets import PointerCursorFilter

logger = logging.getLogger("claude_code_coach.app")


def _app_icon_path() -> Path:
    """Where the app icon lives, for both dev and a packaged build.

    `packaging/build.ps1`'s PyInstaller `--icon` only stamps the .exe
    file's own icon (what Explorer/shortcuts show) - Qt does not pick
    that up for the *running* window or taskbar icon, which is why an
    otherwise-correct build still showed a blank/default icon in both
    places. `QApplication.setWindowIcon()` below is what actually fixes
    that, and needs an actual image file to load - `--add-data` in
    build.ps1 ships `icon.ico` into the frozen app's resource directory
    (`sys._MEIPASS`, valid for onedir too, not just onefile) for exactly
    this to find.
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        return base / "icon.ico"
    repo_root = Path(__file__).resolve().parent.parent
    ico = repo_root / "packaging" / "assets" / "icon.ico"
    if ico.exists():
        return ico
    return repo_root / "vscode-extension" / "icon.png"


def run() -> int:
    init_db()

    app = QApplication(sys.argv)
    app.setApplicationName("Claude Code Coach")
    app.setWindowIcon(QIcon(str(_app_icon_path())))
    app.setStyleSheet(STYLESHEET)
    # UI stabilization pass (docs/UI_STABILIZATION_AUDIT.md, Issue 4): restores
    # the pointer-cursor UX theme.py's invalid QSS `cursor` rules used to
    # (silently, incorrectly) promise. Kept alive for the app's lifetime by
    # parenting it to `app` itself.
    cursor_filter = PointerCursorFilter(app)
    app.installEventFilter(cursor_filter)

    window = MainWindow()
    # Native maximize, not a manual geometry calculation: `setFixedSize()` to
    # QScreen.availableGeometry() (tried previously) sets the WIDGET's own
    # size to the full work area, but that's the client area only — Qt then
    # adds the title bar/frame on top of it, so the actual window ends up
    # taller than the work area and its bottom edge lands under the
    # taskbar. That was the real cause of content "disappearing behind the
    # taskbar": the window itself was oversized, not the page content.
    # showMaximized() instead asks Windows to maximize the window, which
    # correctly accounts for the frame and the taskbar on whichever monitor
    # the window is on. Restoring back down is blocked separately in
    # MainWindow.changeEvent (still native — no manual geometry math there
    # either), so the window stays maximized without this app computing
    # screen geometry itself at all.
    window.showMaximized()

    if window.controller.scan_on_startup:
        window.controller.scan_environment_async(on_done=lambda snap: window.controller.refresh_all())

    # Phase 4C, Step 7/8/9 (single runtime-event-draining owner): a live,
    # compatible Coach service — a standalone `python -m
    # claude_code_coach.service` process, or another running desktop
    # instance — may already be reachable. If so, this process must NOT
    # also start its own embedded copy: two independently-running drain
    # loops would both poll the same runtime_events/*.jsonl files with no
    # coordination between them. window.controller.backend_client already
    # exists (constructed in CoachController.__init__) specifically so this
    # one check has a single place to live, reused by
    # CoachController.poll_runtime()'s own per-call guard and by
    # coach_backend_summary()'s Dashboard/Settings readout — see
    # docs/DESKTOP_SERVICE_MIGRATION.md for the full design.
    #
    # This process still starts its embedded copy (the temporary Step 9
    # fallback) whenever no other service is already live — including the
    # ordinary case of being the FIRST Coach process on this machine, and
    # the desktop-closes-and-reopens case (Scenario D) where no standalone
    # service happens to be running. A failed bind (e.g. the port is
    # otherwise in use) is still caught and logged non-fatally either way —
    # see service/lifecycle.py.
    if window.controller.backend_client.is_available():
        logger.info(
            "A Coach service is already running and reachable — this process will act as "
            "a client instead of starting its own embedded copy (Phase 4C single-owner rule)."
        )
    else:
        start_service()
        app.aboutToQuit.connect(stop_service)
    # Give any in-flight background scan (environment or usage) a bounded
    # chance to actually stop before Qt tears down its QThread — see
    # CoachController.shutdown()'s docstring for the real bug this closes.
    app.aboutToQuit.connect(window.controller.shutdown)

    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
