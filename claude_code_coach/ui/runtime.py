"""Runtime page: real Claude Code hook events, when configured.

Every displayed state is one of the explicit values in
`runtime.models.ConnectionState` (spec section 2) — there is no code path
that invents a "live" event.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from claude_code_coach.runtime.models import ConnectionState

from . import theme
from .widgets import Badge, EmptyState, Panel, SectionHeader, StatCard, page_header

POLL_INTERVAL_MS = 3000

_STATE_LABELS = {
    ConnectionState.LIVE: ("● LIVE", theme.GOOD),
    ConnectionState.CONNECTED: ("● CONNECTED (idle)", theme.WARN),
    ConnectionState.CONFIGURED: ("○ CONFIGURED (no events yet)", theme.INFO),
    ConnectionState.NOT_CONFIGURED: ("○ NOT CONFIGURED", theme.TEXT_MUTED),
    ConnectionState.UNAVAILABLE: ("○ NOT CONNECTED", theme.TEXT_MUTED),
    ConnectionState.UNKNOWN: ("○ UNKNOWN", theme.TEXT_MUTED),
}

_LEVEL_COLOR = {"high": theme.BAD, "medium": theme.WARN, "low": theme.INFO}


class SignalCard(Panel):
    def __init__(self, signal, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        top = QHBoxLayout()
        title = QLabel(signal.message)
        title.setWordWrap(True)
        title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {theme.TEXT_PRIMARY};")
        top.addWidget(title, 1)
        top.addWidget(Badge(signal.level.upper(), _LEVEL_COLOR.get(signal.level, theme.INFO)))
        layout.addLayout(top)

        for label, text in (("What happened", signal.what_happened),
                             ("Why it matters", signal.why_it_matters),
                             ("Try", signal.try_instead)):
            if text:
                lbl = QLabel(f"{label}: {text}")
                lbl.setWordWrap(True)
                lbl.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11.5px;")
                layout.addWidget(lbl)


class Runtime(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header(
            "Runtime",
            "Real Claude Code activity, observed through hooks you explicitly install — "
            "never fabricated. Prompt-based coaching keeps working with or without this.",
        ))

        # -- connection + controls row -------------------------------------------
        conn_row = QHBoxLayout()
        self.state_label = QLabel("")
        self.state_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        conn_row.addWidget(self.state_label)
        conn_row.addStretch()

        self.enabled_checkbox = QCheckBox("Runtime Coach enabled")
        self.enabled_checkbox.toggled.connect(self._on_toggle_enabled)
        conn_row.addWidget(self.enabled_checkbox)
        outer.addLayout(conn_row)

        self.last_event_label = QLabel("")
        self.last_event_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        outer.addWidget(self.last_event_label)

        button_row = QHBoxLayout()
        self.install_button = QPushButton("Install Runtime Hooks…")
        self.install_button.setObjectName("Secondary")
        self.install_button.clicked.connect(self._on_install)
        self.uninstall_button = QPushButton("Remove Runtime Hooks")
        self.uninstall_button.setObjectName("Secondary")
        self.uninstall_button.clicked.connect(self._on_uninstall)
        button_row.addWidget(self.install_button)
        button_row.addWidget(self.uninstall_button)
        button_row.addStretch()
        outer.addLayout(button_row)

        privacy = QLabel(
            "🔒 Read-only: never executes Skill/Agent/MCP code. Prompt text is not stored "
            "unless you opt in on Settings. No network calls, ever."
        )
        privacy.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10.5px;")
        outer.addWidget(privacy)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(16)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.content_layout.addWidget(SectionHeader("CURRENT SESSION"))
        self.session_cards = QHBoxLayout()
        self.session_cards.setSpacing(14)
        self.content_layout.addLayout(self.session_cards)

        self.content_layout.addWidget(SectionHeader("COACHING SIGNALS"))
        self.signals_layout = QVBoxLayout()
        self.signals_layout.setSpacing(10)
        self.content_layout.addLayout(self.signals_layout)

        self.content_layout.addWidget(SectionHeader("RECENT EVENTS"))
        self.timeline = QTextEdit()
        self.timeline.setReadOnly(True)
        self.timeline.setMaximumHeight(220)
        self.content_layout.addWidget(self.timeline)

        self.content_layout.addStretch()

        # QTimer created only after super().__init__() has fully run.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_and_refresh)
        self._poll_timer.start()

        self.refresh()

    def _clear(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear(item.layout())

    def _poll_and_refresh(self) -> None:
        self.controller.poll_runtime()
        self.refresh()

    def refresh(self) -> None:
        self.enabled_checkbox.blockSignals(True)
        self.enabled_checkbox.setChecked(self.controller.runtime_enabled)
        self.enabled_checkbox.blockSignals(False)

        status = self.controller.runtime_status()
        label, color = _STATE_LABELS.get(status.state, ("UNKNOWN", theme.TEXT_MUTED))
        if status.state == ConnectionState.UNAVAILABLE and not self.controller.runtime_enabled:
            label = "○ PAUSED"
        self.state_label.setText(label)
        self.state_label.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {color};")
        self.last_event_label.setText(
            f"Last event: {status.last_event_at}" if status.last_event_at
            else "No runtime events observed yet."
        )

        self._clear(self.session_cards)
        s = status.current_session
        self.session_cards.addWidget(StatCard("PROMPTS", str(s.prompts) if s else "--"))
        self.session_cards.addWidget(StatCard("TOOL CALLS", str(s.tool_calls) if s else "--"))
        self.session_cards.addWidget(StatCard("SEARCHES", str(s.searches) if s else "--"))
        self.session_cards.addWidget(StatCard("READS", str(s.reads) if s else "--"))
        self.session_cards.addWidget(StatCard("EDITS", str(s.edits) if s else "--"))
        self.session_cards.addWidget(StatCard("SKILLS/AGENTS", str(s.skills_or_agents) if s else "--"))

        self._clear(self.signals_layout)
        if not status.signals:
            msg = (
                "Runtime integration unavailable. Prompt-based coaching and environment "
                "awareness continue to work normally."
                if status.state in (ConnectionState.NOT_CONFIGURED, ConnectionState.UNAVAILABLE)
                else "No coaching signals right now."
            )
            self.signals_layout.addWidget(EmptyState(msg))
        else:
            for sig in status.signals:
                self.signals_layout.addWidget(SignalCard(sig))

        self._refresh_timeline(s.session_id if s else None)

    def _refresh_timeline(self, session_id: str | None) -> None:
        if not session_id:
            self.timeline.setPlainText("")
            return
        from claude_code_coach.database import db
        events = db.fetch_runtime_events(session_id, limit=200)[-50:]
        lines = []
        for e in events:
            ts = e["received_at"].split("T")[-1] if "T" in e["received_at"] else e["received_at"]
            tool = f" [{e['tool_name']}]" if e.get("tool_name") else ""
            lines.append(f"{ts}  {e['event_type']}{tool}")
        self.timeline.setPlainText("\n".join(lines) if lines else "No events in this session yet.")

    def _on_toggle_enabled(self, checked: bool) -> None:
        self.controller.set_runtime_enabled(checked)
        self.refresh()

    def _on_install(self) -> None:
        default_path = str(self.controller.default_hooks_settings_path())
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Install Runtime Hooks into settings.json", default_path,
            "JSON files (*.json)",
        )
        if not path_str:
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Install Runtime Hooks")
        box.setText(
            f"This will add hook entries to:\n\n{path_str}\n\n"
            "for SessionStart, SessionEnd, UserPromptSubmit, PreToolUse, PostToolUse, "
            "Stop, SubagentStop, PreCompact, Notification, and PermissionRequest.\n\n"
            "Any existing hooks in this file are preserved. This can be undone with "
            "'Remove Runtime Hooks'."
        )
        confirm = box.addButton("Install", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not confirm:
            return

        try:
            result = self.controller.install_runtime_hooks(path_str)
        except ValueError as exc:
            QMessageBox.critical(self, "Install failed", str(exc))
            return
        QMessageBox.information(
            self, "Hooks installed",
            f"Added hooks for: {', '.join(result['added_events']) or '(already installed)'}",
        )
        self.refresh()

    def _on_uninstall(self) -> None:
        path = self.controller.runtime_coach.hooks_install_path() or str(
            self.controller.default_hooks_settings_path()
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Remove Runtime Hooks")
        box.setText(f"Remove this app's hook entries from:\n\n{path}\n\n"
                    "Only entries this app added are removed; everything else is left as-is.")
        confirm = box.addButton("Remove", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not confirm:
            return

        try:
            result = self.controller.uninstall_runtime_hooks(path)
        except ValueError as exc:
            QMessageBox.critical(self, "Remove failed", str(exc))
            return
        QMessageBox.information(
            self, "Hooks removed",
            f"Removed hooks for: {', '.join(result['removed_events']) or '(none found)'}",
        )
        self.refresh()
