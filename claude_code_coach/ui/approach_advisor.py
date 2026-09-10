"""Approach Advisor (spec Feature 2): a focused "how should I work on this?"
tool — describe the task, get the Recommended Approach only (no full
prompt-quality breakdown; that lives in the Prompt Inspector).
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from . import theme
from .widgets import Panel, SectionHeader, page_header


class ApproachAdvisor(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header(
            "Approach Advisor",
            "Describe what you're trying to accomplish — get a recommendation for "
            "how to work with Claude Code on it, not a prompt-quality score.",
        ))

        self.input = QTextEdit()
        self.input.setPlaceholderText(
            "e.g. Investigate why our API tests are failing.\n"
            "e.g. Investigate why the test suite is slow across backend, database "
            "and frontend."
        )
        self.input.setMaximumHeight(140)
        outer.addWidget(self.input)

        button_row = QHBoxLayout()
        self.button = QPushButton("Get Recommended Approach")
        self.button.clicked.connect(self._on_get_approach)
        button_row.addWidget(self.button)
        button_row.addStretch()
        outer.addLayout(button_row)

        outer.addWidget(SectionHeader("RECOMMENDED APPROACH"))
        panel = Panel()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 16, 18, 16)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(260)
        panel_layout.addWidget(self.output)
        outer.addWidget(panel, 1)

        note = QLabel(
            "Evaluated independently across three evidence sources: this task, your "
            "scanned Claude Code environment, and (if enabled) your live runtime "
            "session — never fabricated, never collapsed into one score."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10.5px;")
        outer.addWidget(note)

    def refresh(self) -> None:
        pass

    def _on_get_approach(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            self.output.setPlainText("Describe a task above first.")
            return

        report = self.controller.recommend_approach(text)
        lines = []
        for rec in report.recommendations:
            lines.append(f"{rec.icon} {rec.message}")
            if rec.what_happened:
                lines.append(f"    What happened: {rec.what_happened}")
            if rec.why_it_matters:
                lines.append(f"    Why it matters: {rec.why_it_matters}")
            if rec.try_instead:
                lines.append(f"    Try: {rec.try_instead}")
            lines.append("")
        self.output.setPlainText("\n".join(lines).strip())
