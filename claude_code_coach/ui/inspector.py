"""Prompt Inspector: real-time Live Coach + Analyze-and-save.

IMPORTANT (spec section 8): QTimer(self) is created only after
super().__init__() has completed. The live analyzer never writes to SQLite
on every keystroke — only the Analyze button persists a prompt.

V5 (spec Feature 13) adds Suggested Prompt / Recommended Approach /
Session-Context sections, each independently understandable — prompt
quality, environment evidence, and session/runtime evidence are never
collapsed into one combined verdict.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from claude_code_coach.analyzer import AnalysisResult
from claude_code_coach.analyzer.prompt_rewriter import PromptCategory
from claude_code_coach.integration import build_environment_feedback

from . import theme
from .widgets import Panel, ScorePill, SectionHeader, page_header
from .workshop_lessons import DIMENSION_LESSONS, OPPORTUNITY_LESSONS

DEBOUNCE_MS = 400

DIMENSION_LABELS = {
    "goal": "Goal",
    "scope": "Scope",
    "investigation": "Search first",
    "constraints": "Constraints",
    "done": "Definition of done",
    "output": "Output control",
}

PLACEHOLDER = (
    "Paste or type a Claude Code prompt here...\n\n"
    "Example:\n"
    "Find where the login request is handled.\n"
    "Only inspect src/auth/.\n"
    "Identify the root cause before modifying files.\n"
    "Done when the authentication tests pass.\n"
    "Return only root cause, changed files and test result."
)


class IndicatorRow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._labels: list[QLabel] = []

    def set_dimensions(self, dimensions: dict) -> None:
        for lbl in self._labels:
            lbl.deleteLater()
        self._labels = []

        for key, title in DIMENSION_LABELS.items():
            dim = dimensions.get(key)
            if dim is None or dim.status == "na":
                continue
            if dim.status == "clear":
                icon, color = "✓", theme.GOOD
            elif dim.status == "partial":
                icon, color = "◐", theme.WARN
            else:
                icon, color = "⚠", theme.WARN
            label = QLabel(f"{icon}  {title}")
            label.setStyleSheet(f"color: {color}; font-size: 12.5px; padding: 1px 0;")
            self._layout.addWidget(label)
            self._labels.append(label)

        if not self._labels:
            placeholder = QLabel("Start typing to see live coaching.")
            placeholder.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
            self._layout.addWidget(placeholder)
            self._labels.append(placeholder)


class Inspector(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._last_suggestion_text: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header(
            "Prompt Inspector",
            "Live Coach analyzes as you type. Nothing is saved until you press Analyze.",
        ))

        splitter = QSplitter(Qt.Horizontal)
        # QSplitter's default vertical size policy is Preferred, not
        # Expanding — without this, it competes with the header labels for
        # leftover vertical space instead of dominating it, stretching the
        # title/subtitle labels into big empty boxes.
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # -- left: editor --------------------------------------------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 8, 0, 0)

        self.editor = QTextEdit()
        self.editor.setPlaceholderText(PLACEHOLDER)
        self.editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.editor)

        button_row = QHBoxLayout()
        self.analyze_button = QPushButton("Analyze && Save")
        self.analyze_button.clicked.connect(self._on_analyze)
        self.copy_suggestion_button = QPushButton("Copy Suggested Prompt")
        self.copy_suggestion_button.setObjectName("Secondary")
        self.copy_suggestion_button.clicked.connect(self._on_copy_suggestion)
        self.copy_suggestion_button.setEnabled(False)
        self.use_suggestion_button = QPushButton("Use as New Prompt")
        self.use_suggestion_button.setObjectName("Secondary")
        self.use_suggestion_button.clicked.connect(self._on_use_suggestion)
        self.use_suggestion_button.setEnabled(False)
        self.saved_label = QLabel("")
        self.saved_label.setStyleSheet(f"color: {theme.GOOD}; font-size: 12px;")
        button_row.addWidget(self.analyze_button)
        button_row.addWidget(self.copy_suggestion_button)
        button_row.addWidget(self.use_suggestion_button)
        button_row.addWidget(self.saved_label)
        button_row.addStretch()
        left_layout.addLayout(button_row)

        # -- right: live coach (scrollable — several independent sections) ------
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setMinimumWidth(340)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)
        right_layout.setSpacing(14)

        top_panel = Panel()
        top_layout = QVBoxLayout(top_panel)
        top_layout.setContentsMargins(18, 16, 18, 16)
        top_layout.setSpacing(10)
        top_layout.addWidget(SectionHeader("PROMPT QUALITY"))
        self.score_pill = ScorePill()
        top_layout.addWidget(self.score_pill)
        self.task_type_label = QLabel("")
        self.task_type_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11.5px;")
        top_layout.addWidget(self.task_type_label)
        self.indicators = IndicatorRow()
        top_layout.addWidget(self.indicators)
        right_layout.addWidget(top_panel)

        right_layout.addWidget(SectionHeader("FEEDBACK"))
        self.feedback = QTextEdit()
        self.feedback.setReadOnly(True)
        self.feedback.setMinimumHeight(140)
        right_layout.addWidget(self.feedback)

        right_layout.addWidget(SectionHeader("SUGGESTED PROMPT"))
        self.suggestion_text = QTextEdit()
        self.suggestion_text.setReadOnly(True)
        self.suggestion_text.setMaximumHeight(140)
        right_layout.addWidget(self.suggestion_text)

        right_layout.addWidget(SectionHeader("RECOMMENDED APPROACH"))
        self.approach_text = QTextEdit()
        self.approach_text.setReadOnly(True)
        self.approach_text.setMaximumHeight(150)
        right_layout.addWidget(self.approach_text)

        right_layout.addWidget(SectionHeader("SESSION / CONTEXT"))
        self.session_label = QLabel("")
        self.session_label.setWordWrap(True)
        self.session_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11.5px;")
        right_layout.addWidget(self.session_label)

        disclaimer = QLabel(
            "Local Context Efficiency Score — a coaching heuristic, not an "
            "official Anthropic/Claude metric or a measurement of token savings."
        )
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 10.5px;")
        right_layout.addWidget(disclaimer)
        right_layout.addStretch()

        right_scroll.setWidget(right)

        splitter.addWidget(left)
        splitter.addWidget(right_scroll)
        splitter.setSizes([720, 420])
        outer.addWidget(splitter)

        # QTimer is created only after super().__init__() has fully run.
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._live_analyze)
        self.editor.textChanged.connect(self._debounce.start)

        self._render_result(None)

    # ------------------------------------------------------------------
    def _live_analyze(self) -> None:
        text = self.editor.toPlainText()
        if not text.strip():
            self._render_result(None)
            return
        result = self.controller.analyze(text)
        self._render_result(result)

    def _render_result(self, result: AnalysisResult | None) -> None:
        self.saved_label.setText("")
        if result is None:
            self.score_pill.set_score(None, "")
            self.task_type_label.setText("")
            self.indicators.set_dimensions({})
            self.feedback.setPlainText("")
            self.suggestion_text.setPlainText("")
            self.approach_text.setPlainText("")
            self.session_label.setText("")
            self._set_suggestion(None)
            return

        self.score_pill.set_score(result.score, result.rating)
        self.task_type_label.setText(f"Task type: {result.task_type.replace('_', ' ')}")
        self.indicators.set_dimensions(result.dimensions)

        workshop = self.controller.workshop_mode
        lines = []
        if result.good:
            lines.append("GOOD HABITS")
            lines.extend(f"✓ {x}" for x in result.good)
            lines.append("")
        if result.warnings:
            lines.append("IMPROVEMENTS")
            lines.extend(f"⚠ {w}" for w in result.warnings)
            if workshop:
                for key, dim in result.dimensions.items():
                    if dim.status in ("missing", "partial") and key in DIMENSION_LESSONS:
                        why, try_this = DIMENSION_LESSONS[key]
                        label = DIMENSION_LABELS.get(key, key)
                        lines.append(f"    [{label}] WHY THIS MATTERS: {why}")
                        lines.append(f"    TRY THIS: {try_this}")
            lines.append("")
        if result.opportunities:
            lines.append("OPPORTUNITIES")
            for o in result.opportunities:
                lines.append(f"→ {o.message}")
                if workshop and o.kind in OPPORTUNITY_LESSONS:
                    why, try_this = OPPORTUNITY_LESSONS[o.kind]
                    lines.append(f"    WHY THIS MATTERS: {why}")
                    lines.append(f"    TRY THIS: {try_this}")

        env_lines = self._environment_lines(result)
        if env_lines:
            if lines:
                lines.append("")
            lines.append("ENVIRONMENT")
            lines.extend(env_lines)

        if not lines:
            lines.append("No feedback yet.")
        self.feedback.setPlainText("\n".join(lines))

        text = self.editor.toPlainText()
        suggestion = self.controller.suggest_prompt(text, result)
        self._render_suggestion(suggestion)

        approach = self.controller.recommend_approach(text, result)
        self._render_approach(approach)

        self._render_session()

    def _render_suggestion(self, suggestion) -> None:
        if suggestion.category == PromptCategory.EMPTY:
            self.suggestion_text.setPlainText("")
            self._set_suggestion(None)
            return

        if suggestion.suggested_text:
            self.suggestion_text.setPlainText(f"{suggestion.message}\n\n{suggestion.suggested_text}")
            self._set_suggestion(suggestion.suggested_text)
        else:
            self.suggestion_text.setPlainText(suggestion.message)
            self._set_suggestion(None)

    def _set_suggestion(self, text: str | None) -> None:
        self._last_suggestion_text = text
        self.copy_suggestion_button.setEnabled(bool(text))
        self.use_suggestion_button.setEnabled(bool(text))

    def _render_approach(self, report) -> None:
        lines = []
        for rec in report.recommendations:
            lines.append(f"{rec.icon} {rec.message}")
            if self.controller.workshop_mode and rec.why_it_matters:
                lines.append(f"    WHY THIS MATTERS: {rec.why_it_matters}")
            if self.controller.workshop_mode and rec.try_instead:
                lines.append(f"    TRY THIS: {rec.try_instead}")
        self.approach_text.setPlainText("\n".join(lines) if lines else "No specific recommendation.")

    def _render_session(self) -> None:
        if not self.controller.runtime_enabled:
            self.session_label.setText("Runtime coaching is off — no session data available.")
            return
        status = self.controller.runtime_status()
        if not status.current_session:
            self.session_label.setText(
                "No active runtime session. Prompt quality above is unaffected by this."
            )
            return
        s = status.current_session
        health = f"{status.context_health}%" if status.context_health is not None else "n/a"
        self.session_label.setText(
            f"Current session: {s.prompts} prompt(s), {s.tool_calls} tool call(s). "
            f"Context health: {health}. (Prompt quality is scored independently of this.)"
        )

    def _environment_lines(self, result: AnalysisResult) -> list[str]:
        """Correlate this prompt with the real, scanned environment.

        Only ever runs against an actual scanned snapshot — if nothing has
        been scanned yet, this section is simply omitted rather than
        guessing (spec section 1).
        """
        snapshot = self.controller.environment_snapshot
        if snapshot is None:
            return []

        fb = build_environment_feedback(
            self.editor.toPlainText(), result, snapshot.skills, snapshot.agents, snapshot.claude_md
        )
        lines: list[str] = []

        if fb.skill_state == "existing":
            lines.append(
                f"✓ DETECTED Skill — {fb.skill_match.name} "
                f"({fb.skill_match.confidence} confidence match)"
            )
            lines.append(
                "   This task appears related to an existing Skill. Consider using "
                "it instead of repeating the workflow manually."
            )
        elif fb.skill_state == "candidate":
            lines.append(f"🔧 INFERRED — {fb.skill_candidate_message}")

        if fb.agent_state == "existing":
            lines.append(
                f"✓ DETECTED Agent — {fb.agent_match.name} "
                f"({fb.agent_match.confidence} confidence match)"
            )
            lines.append("   An existing Agent may be relevant to this task.")
        elif fb.agent_state == "candidate":
            lines.append(f"🤖 INFERRED — {fb.agent_candidate_message}")

        if fb.claude_md_duplicate:
            lines.append(
                f"📝 Existing project instruction — this appears to already exist "
                f"in {fb.claude_md_duplicate.path}. Consider relying on the "
                f"project instruction instead of repeating it here."
            )

        return lines

    def _on_analyze(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "No prompt", "Type or paste a prompt first.")
            return

        result = self.controller.analyze(text)
        self.controller.save(result)
        self._render_result(result)
        self.saved_label.setText("✓ Saved to history")
        self.controller.refresh_all()

    def _on_copy_suggestion(self) -> None:
        if not self._last_suggestion_text:
            return
        QGuiApplication.clipboard().setText(self._last_suggestion_text)
        self.saved_label.setStyleSheet(f"color: {theme.GOOD};")
        self.saved_label.setText("✓ Copied suggested prompt")

    def _on_use_suggestion(self) -> None:
        if not self._last_suggestion_text:
            return
        self.editor.setPlainText(self._last_suggestion_text)
