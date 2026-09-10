"""Background worker so environment scanning never blocks the UI thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class EnvironmentScanWorker(QObject):
    finished = Signal(object)  # EnvironmentSnapshot
    failed = Signal(str)

    def __init__(self, provider):
        super().__init__()
        self.provider = provider

    def run(self) -> None:
        try:
            snapshot = self.provider.scan()
        except Exception as exc:  # noqa: BLE001 - never let a scan crash the worker thread
            self.failed.emit(str(exc))
            return
        self.finished.emit(snapshot)
