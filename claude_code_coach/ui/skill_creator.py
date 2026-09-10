"""Skill Creator (spec Feature 3): deterministic, template-based, and never
writes without Generate Preview -> explicit Save.
"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QTextEdit, QVBoxLayout, QWidget,
)

from claude_code_coach.creators import SkillDraft

from . import theme
from .widgets import Panel, SectionHeader, page_header

_FIELD_SPECS = (
    ("purpose", "Purpose", False),
    ("when_to_use", "When should this Skill be used?", False),
    ("workflow", "Workflow", True),
    ("rules", "Rules", True),
    ("constraints", "Constraints", True),
    ("avoid", "Things to avoid", True),
    ("expected_output", "Expected output", False),
    ("examples", "Examples / reference (optional)", True),
)


class SkillCreator(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header(
            "Skill Creator",
            "Turn a repeated workflow into a reusable Skill. Nothing is written "
            "until you explicitly save.",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form_layout = QVBoxLayout(content)
        form_layout.setSpacing(10)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        form_layout.addWidget(QLabel("Skill name (kebab-case, e.g. security-review)"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("security-review")
        form_layout.addWidget(self.name_edit)

        self.fields: dict[str, QTextEdit] = {}
        for key, label, tall in _FIELD_SPECS:
            form_layout.addWidget(QLabel(label))
            edit = QTextEdit()
            edit.setMaximumHeight(120 if tall else 70)
            self.fields[key] = edit
            form_layout.addWidget(edit)

        button_row = QHBoxLayout()
        self.preview_button = QPushButton("Generate Preview")
        self.preview_button.clicked.connect(self._on_generate_preview)
        self.save_button = QPushButton("Save to Project")
        self.save_button.setObjectName("Secondary")
        self.save_button.clicked.connect(self._on_save)
        self.copy_button = QPushButton("Copy SKILL.md")
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

        form_layout.addWidget(SectionHeader("PREVIEW: .claude/skills/<name>/SKILL.md"))
        preview_panel = Panel()
        preview_layout = QVBoxLayout(preview_panel)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMinimumHeight(260)
        preview_layout.addWidget(self.preview_text)
        form_layout.addWidget(preview_panel)

        self._load_draft()

    # -- draft persistence --------------------------------------------------
    def _current_draft(self) -> SkillDraft:
        return SkillDraft(
            name=self.name_edit.text().strip(),
            purpose=self.fields["purpose"].toPlainText(),
            when_to_use=self.fields["when_to_use"].toPlainText(),
            workflow=self.fields["workflow"].toPlainText(),
            rules=self.fields["rules"].toPlainText(),
            constraints=self.fields["constraints"].toPlainText(),
            avoid=self.fields["avoid"].toPlainText(),
            expected_output=self.fields["expected_output"].toPlainText(),
            examples=self.fields["examples"].toPlainText(),
        )

    def _load_draft(self) -> None:
        draft = self.controller.load_skill_draft()
        if not draft:
            return
        self.name_edit.setText(draft.get("name", ""))
        for key in self.fields:
            self.fields[key].setPlainText(draft.get(key, ""))

    def _persist_draft(self) -> None:
        d = self._current_draft()
        self.controller.save_skill_draft_progress({
            "name": d.name, "purpose": d.purpose, "when_to_use": d.when_to_use,
            "workflow": d.workflow, "rules": d.rules, "constraints": d.constraints,
            "avoid": d.avoid, "expected_output": d.expected_output, "examples": d.examples,
        })

    def refresh(self) -> None:
        pass  # form state is user-driven; nothing external to sync on navigation

    # -- actions ------------------------------------------------------------
    def _on_generate_preview(self) -> None:
        draft = self._current_draft()
        self._persist_draft()
        validation = self.controller.validate_skill(draft)

        if not validation.ok:
            self.message_label.setStyleSheet(f"color: {theme.BAD};")
            self.message_label.setText("⚠ " + "  ".join(validation.errors))
            self.preview_text.setPlainText("")
            return

        self.preview_text.setPlainText(self.controller.preview_skill(draft))
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
        self.message_label.setText("✓ Copied SKILL.md to clipboard.")

    def _on_save(self) -> None:
        draft = self._current_draft()
        validation = self.controller.validate_skill(draft)
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
        if self.controller.skill_already_exists(draft.name):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Skill already exists")
            box.setText(
                f"A Skill named '{draft.name}' already exists.\n\n"
                f"Overwrite it with this new content?"
            )
            confirm = box.addButton("Overwrite", QMessageBox.DestructiveRole)
            box.addButton("Cancel", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not confirm:
                return
            overwrite = True

        try:
            result = self.controller.save_skill_file(draft, overwrite=overwrite)
        except (ValueError, FileExistsError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return

        QMessageBox.information(self, "Skill saved", f"Saved to:\n{result['path']}")
        self.message_label.setStyleSheet(f"color: {theme.GOOD};")
        self.message_label.setText(f"✓ Saved to {result['path']}")
