"""Background worker so scanning ~/.claude/projects/ for real token usage
never blocks the UI thread — the same reasoning as env_worker.py's
EnvironmentScanWorker, and it matters even more here: transcript history
only grows over time, so a synchronous scan gets slower with every session
a person runs.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from claude_code_coach.usage import build_usage_summary


class UsageScanWorker(QObject):
    finished = Signal(object)  # UsageSummary
    failed = Signal(str)

    def run(self) -> None:
        try:
            summary = build_usage_summary()
        except Exception as exc:  # noqa: BLE001 - never let a scan crash the worker thread
            self.failed.emit(str(exc))
            return
        self.finished.emit(summary)
