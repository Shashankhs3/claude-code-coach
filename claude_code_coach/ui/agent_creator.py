"""Agent Creator (spec Feature 4): a delegated specialist for a repeatable,
independent type of work — not "use this for every hard task."
"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from claude_code_coach.creators import AgentDraft

from . import theme
from .widgets import Panel, SectionHeader, page_header

_FIELD_SPECS = (
    ("purpose", "Purpose", False),
    ("role", "Role", False),
    ("responsibilities", "Responsibilities", True),
    ("investigation_instructions", "Investigation instructions", True),
    ("allowed_actions", "Allowed actions", True),
    ("restrictions", "Restrictions", True),
    ("expected_output", "Expected output", False),
    ("verification_requirements", "Verification requirements", False),
)


class AgentCreator(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header(
            "Agent Creator",
            "Agent = delegated specialist work for a repeatable, independent "
            "investigation — not something every difficult task needs.",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form_layout = QVBoxLayout(content)
        form_layout.setSpacing(10)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        form_layout.addWidget(QLabel("Agent name (kebab-case, e.g. test-investigator)"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("test-investigator")
        form_layout.addWidget(self.name_edit)

        self.fields: dict[str, QTextEdit] = {}
        for key, label, tall in _FIELD_SPECS:
            form_layout.addWidget(QLabel(label))
            edit = QTextEdit()
            edit.setMaximumHeight(120 if tall else 70)
            self.fields[key] = edit
            form_layout.addWidget(edit)

        self.may_modify_checkbox = QCheckBox("This Agent may modify source files (default: read-only)")
        form_layout.addWidget(self.may_modify_checkbox)

        button_row = QHBoxLayout()
        self.preview_button = QPushButton("Generate Preview")
        self.preview_button.clicked.connect(self._on_generate_preview)
        self.save_button = QPushButton("Save to Project")
        self.save_button.setObjectName("Secondary")
        self.save_button.clicked.connect(self._on_save)
        self.copy_button = QPushButton("Copy Agent Definition")
        self.copy_button.setObjectName("Secondary")
        self.copy_button.clicked.connect(self._on_copy)
        button_row.addWidget(self.preview_button)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.copy_button)
        button_row.addStretch()
        form_layout.addLayout(button_row)

        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        form_layout.addWidget(self.message_label)

        format_note = QLabel(
            "Uses the same frontmatter convention (name/description + markdown body) "
            "this app's Environment scanner already reads from real Claude Code Agent "
            "files. No experimental activation fields are added."
        )
        format_note.setWordWrap(True)
        format_note.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10.5px;")
        form_layout.addWidget(format_note)

        form_layout.addWidget(SectionHeader("PREVIEW: .claude/agents/<name>.md"))
        preview_panel = Panel()
        preview_layout = QVBoxLayout(preview_panel)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(260)
        preview_layout.addWidget(self.preview_text)
        form_layout.addWidget(preview_panel)

        self._load_draft()

    def _current_draft(self) -> AgentDraft:
        return AgentDraft(
            name=self.name_edit.text().strip(),
            purpose=self.fields["purpose"].toPlainText(),
            role=self.fields["role"].toPlainText(),
            responsibilities=self.fields["responsibilities"].toPlainText(),
            investigation_instructions=self.fields["investigation_instructions"].toPlainText(),
            allowed_actions=self.fields["allowed_actions"].toPlainText(),
            restrictions=self.fields["restrictions"].toPlainText(),
            may_modify_source=self.may_modify_checkbox.isChecked(),
            expected_output=self.fields["expected_output"].toPlainText(),
            verification_requirements=self.fields["verification_requirements"].toPlainText(),
        )

    def _load_draft(self) -> None:
        draft = self.controller.load_agent_draft()
        if not draft:
            return
        self.name_edit.setText(draft.get("name", ""))
        for key in self.fields:
            self.fields[key].setPlainText(draft.get(key, ""))
        self.may_modify_checkbox.setChecked(bool(draft.get("may_modify_source", False)))

    def _persist_draft(self) -> None:
        d = self._current_draft()
        self.controller.save_agent_draft_progress({
            "name": d.name, "purpose": d.purpose, "role": d.role,
            "responsibilities": d.responsibilities,
            "investigation_instructions": d.investigation_instructions,
            "allowed_actions": d.allowed_actions, "restrictions": d.restrictions,
            "may_modify_source": d.may_modify_source,
            "expected_output": d.expected_output,
            "verification_requirements": d.verification_requirements,
        })

    def refresh(self) -> None:
        pass

    def _on_generate_preview(self) -> None:
        draft = self._current_draft()
        self._persist_draft()
        validation = self.controller.validate_agent(draft)

        if not validation.ok:
            self.message_label.setStyleSheet(f"color: {theme.BAD};")
            self.message_label.setText("⚠ " + "  ".join(validation.errors))
            self.preview_text.setPlainText("")
            return

        self.preview_text.setPlainText(self.controller.preview_agent(draft))
        if validation.warnings:
            self.message_label.setStyleSheet(f"color: {theme.WARN};")
            self.message_label.setText("⚠ " + "  ".join(validation.warnings))
        else:
            self.message_label.setStyleSheet(f"color: {theme.GOOD};")
            self.message_label.setText("✓ Preview generated. Review it, then Save to Project.")

    def _on_copy(self) -> None:
        text = self.preview_text.toPlainText()
        if not text:
            QMessageBox.information(self, "Nothing to copy", "Generate a preview first.")
            return
        QGuiApplication.clipboard().setText(text)
        self.message_label.setStyleSheet(f"color: {theme.GOOD};")
        self.message_label.setText("✓ Copied Agent definition to clipboard.")

    def _on_save(self) -> None:
        draft = self._current_draft()
        validation = self.controller.validate_agent(draft)
        if not validation.ok:
            QMessageBox.warning(self, "Cannot save", "\n".join(validation.errors))
            return

        if not self.controller.environment.project_root:
            QMessageBox.warning(
                self, "No project folder",
                "Choose a project folder on the Environment or Settings page first.",
            )
            return

        overwrite = False
        if self.controller.agent_already_exists(draft.name):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Agent already exists")
            box.setText(
                f"An Agent named '{draft.name}' already exists.\n\n"
                f"Overwrite it with this new content?"
            )
            confirm = box.addButton("Overwrite", QMessageBox.DestructiveRole)
            box.addButton("Cancel", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not confirm:
                return
            overwrite = True

        try:
            result = self.controller.save_agent_file(draft, overwrite=overwrite)
        except (ValueError, FileExistsError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return

        QMessageBox.information(self, "Agent saved", f"Saved to:\n{result['path']}")
        self.message_label.setStyleSheet(f"color: {theme.GOOD};")
        self.message_label.setText(f"✓ Saved to {result['path']}")
