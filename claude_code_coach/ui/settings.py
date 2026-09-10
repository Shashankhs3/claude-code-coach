from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from .widgets import Panel, SectionHeader, page_header

_RETENTION_OPTIONS = [
    ("7 days", 7), ("30 days", 30), ("90 days", 90), ("Forever", None),
]


class Settings(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header("Settings", "Local database, privacy, and data management."))

        # -- Privacy -----------------------------------------------------------
        outer.addWidget(SectionHeader("PRIVACY"))
        privacy_panel = Panel()
        privacy_layout = QVBoxLayout(privacy_panel)
        privacy_layout.setContentsMargins(18, 16, 18, 16)
        privacy_label = QLabel(
            "🔒  Local only\n\n"
            "Prompts and analytics remain on this computer in the current version. "
            "No prompts, source code, or database contents are ever sent to an "
            "external API or telemetry service. Environment scanning (below) reads "
            "local Claude Code configuration only — read-only, no network calls, "
            "and any detected secret values are redacted before ever being shown."
        )
        privacy_label.setWordWrap(True)
        privacy_layout.addWidget(privacy_label)
        outer.addWidget(privacy_panel)

        # -- Environment scanning --------------------------------------------------
        outer.addWidget(SectionHeader("ENVIRONMENT SCANNING"))
        env_panel = Panel()
        env_layout = QVBoxLayout(env_panel)
        env_layout.setContentsMargins(18, 16, 18, 16)
        env_layout.setSpacing(10)

        self.project_root_label = QLabel("")
        self.project_root_label.setWordWrap(True)
        env_layout.addWidget(self.project_root_label)

        root_row = QHBoxLayout()
        choose_root_btn = QPushButton("Choose Project Folder")
        choose_root_btn.setObjectName("Secondary")
        choose_root_btn.clicked.connect(self._on_choose_root)
        clear_root_btn = QPushButton("Clear Project Folder")
        clear_root_btn.setObjectName("Secondary")
        clear_root_btn.clicked.connect(self._on_clear_root)
        root_row.addWidget(choose_root_btn)
        root_row.addWidget(clear_root_btn)
        root_row.addStretch()
        env_layout.addLayout(root_row)

        self.scan_startup_checkbox = QCheckBox("Scan Claude Code environment on application startup")
        self.scan_startup_checkbox.toggled.connect(self._on_toggle_scan_startup)
        env_layout.addWidget(self.scan_startup_checkbox)

        outer.addWidget(env_panel)

        # -- Runtime coaching --------------------------------------------------------
        outer.addWidget(SectionHeader("RUNTIME COACHING"))
        runtime_panel = Panel()
        runtime_layout = QVBoxLayout(runtime_panel)
        runtime_layout.setContentsMargins(18, 16, 18, 16)
        runtime_layout.setSpacing(10)

        runtime_note = QLabel(
            "Enable/install hooks on the Runtime page. These settings control what gets "
            "kept once runtime coaching is on."
        )
        runtime_note.setWordWrap(True)
        runtime_layout.addWidget(runtime_note)

        self.collect_content_checkbox = QCheckBox(
            "Store prompt/response text (off by default — only derived signals like word "
            "count and task type are kept otherwise)"
        )
        self.collect_content_checkbox.toggled.connect(self._on_toggle_collect_content)
        runtime_layout.addWidget(self.collect_content_checkbox)

        retention_row = QHBoxLayout()
        retention_row.addWidget(QLabel("Runtime history retention:"))
        self.retention_combo = QComboBox()
        for label, _days in _RETENTION_OPTIONS:
            self.retention_combo.addItem(label)
        self.retention_combo.currentIndexChanged.connect(self._on_retention_changed)
        retention_row.addWidget(self.retention_combo)
        retention_row.addStretch()
        runtime_layout.addLayout(retention_row)

        outer.addWidget(runtime_panel)

        # -- Database ------------------------------------------------------------
        outer.addWidget(SectionHeader("DATABASE"))
        db_panel = Panel()
        db_layout = QVBoxLayout(db_panel)
        db_layout.setContentsMargins(18, 16, 18, 16)
        db_layout.setSpacing(10)

        self.db_info_label = QLabel("")
        self.db_info_label.setWordWrap(True)
        db_layout.addWidget(self.db_info_label)

        button_row = QHBoxLayout()
        export_btn = QPushButton("Export Data")
        export_btn.setObjectName("Secondary")
        export_btn.clicked.connect(self._on_export)
        import_btn = QPushButton("Import Data")
        import_btn.setObjectName("Secondary")
        import_btn.clicked.connect(self._on_import)
        clear_btn = QPushButton("Clear All Local Data")
        clear_btn.setObjectName("Danger")
        clear_btn.clicked.connect(self._on_clear)

        button_row.addWidget(export_btn)
        button_row.addWidget(import_btn)
        button_row.addStretch()
        button_row.addWidget(clear_btn)
        db_layout.addLayout(button_row)

        outer.addWidget(db_panel)
        outer.addStretch()

        self.refresh()

    def refresh(self) -> None:
        info = self.controller.db_info()
        self.db_info_label.setText(
            f"Database location: {info['path']}\n"
            f"Stored prompts: {info['prompt_count']}\n"
            f"Database size: {info['size_human']}"
        )

        root = self.controller.environment.project_root
        self.project_root_label.setText(
            f"Project folder: {root}" if root else
            "Project folder: none selected — the Environment page will only show "
            "user-level (~/.claude) results until one is chosen."
        )
        self.scan_startup_checkbox.blockSignals(True)
        self.scan_startup_checkbox.setChecked(self.controller.scan_on_startup)
        self.scan_startup_checkbox.blockSignals(False)

        self.collect_content_checkbox.blockSignals(True)
        self.collect_content_checkbox.setChecked(self.controller.runtime_collect_content())
        self.collect_content_checkbox.blockSignals(False)

        current_days = self.controller.runtime_retention_days()
        self.retention_combo.blockSignals(True)
        for i, (_label, days) in enumerate(_RETENTION_OPTIONS):
            if days == current_days:
                self.retention_combo.setCurrentIndex(i)
                break
        else:
            self.retention_combo.setCurrentIndex(len(_RETENTION_OPTIONS) - 1)  # Forever
        self.retention_combo.blockSignals(False)

    def _on_export(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export Data", "coach_export.json", "JSON files (*.json)"
        )
        if not path_str:
            return
        try:
            count = self.controller.export_json(Path(path_str))
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Export complete", f"Exported {count} prompt(s).")

    def _on_import(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Import Data", "", "JSON files (*.json)"
        )
        if not path_str:
            return
        try:
            count = self.controller.import_json(Path(path_str))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        QMessageBox.information(self, "Import complete", f"Imported {count} prompt(s).")
        self.refresh()

    def _on_clear(self) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Clear All Local Data")
        box.setText(
            "Delete all prompt history, scores, habits, environment scan results, and "
            "runtime session data? This cannot be undone. (Hook installation and your "
            "preferences here are configuration, not data, and are kept.)"
        )
        cancel_btn = box.addButton("Cancel", QMessageBox.RejectRole)
        delete_btn = box.addButton("Delete Everything", QMessageBox.DestructiveRole)
        box.setDefaultButton(cancel_btn)
        box.exec()

        if box.clickedButton() is delete_btn:
            self.controller.clear_all()
            self.refresh()
            QMessageBox.information(self, "Done", "All local data has been deleted.")

    def _on_choose_root(self) -> None:
        current = self.controller.environment.project_root
        start_dir = str(current) if current else ""
        folder = QFileDialog.getExistingDirectory(self, "Choose Project Folder", start_dir)
        if not folder:
            return
        self.controller.set_project_root(folder)
        self.refresh()

    def _on_clear_root(self) -> None:
        self.controller.set_project_root(None)
        self.refresh()

    def _on_toggle_scan_startup(self, checked: bool) -> None:
        self.controller.set_scan_on_startup(checked)

    def _on_toggle_collect_content(self, checked: bool) -> None:
        self.controller.set_runtime_collect_content(checked)

    def _on_retention_changed(self, index: int) -> None:
        _label, days = _RETENTION_OPTIONS[index]
        self.controller.set_runtime_retention_days(days)
        self.controller.apply_runtime_retention()
