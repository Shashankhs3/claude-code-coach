from __future__ import annotations

from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from claude_code_coach.analytics import skill_candidates
from claude_code_coach.integration.environment_matching import match_skills

from . import theme
from .environment import DetectedItemCard
from .widgets import CandidateCard, EmptyState, SectionHeader, page_header


class Skills(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header(
            "Skills",
            "Real Skills detected in your Claude Code environment, plus repeatable "
            "workflows in your prompt history that may be worth turning into one.",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(12)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # -- Existing (DETECTED) Skills ------------------------------------------
        self.content_layout.addWidget(SectionHeader("EXISTING SKILLS (DETECTED)"))
        self.existing_layout = QVBoxLayout()
        self.existing_layout.setSpacing(10)
        self.content_layout.addLayout(self.existing_layout)

        # -- Skill candidates (INFERRED from history) -----------------------------
        self.content_layout.addWidget(SectionHeader("SKILL CANDIDATES (INFERRED)"))
        self.candidates_layout = QVBoxLayout()
        self.candidates_layout.setSpacing(10)
        self.content_layout.addLayout(self.candidates_layout)

        self.content_layout.addStretch()

        self.refresh()

    def _clear(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear(item.layout())

    def refresh(self) -> None:
        self._clear(self.existing_layout)
        snapshot = self.controller.environment_snapshot
        skills = snapshot.skills if snapshot else []
        if not skills:
            self.existing_layout.addWidget(EmptyState(
                "No Skills detected in your Claude Code environment yet. "
                "Scan on the Environment page after selecting a project folder."
            ))
        else:
            for skill in skills:
                source = skill.source.value if hasattr(skill.source, "value") else str(skill.source)
                self.existing_layout.addWidget(
                    DetectedItemCard(skill.name, skill.description, source, skill.modified)
                )

        self._clear(self.candidates_layout)
        rows = self.controller.history()
        candidates = skill_candidates(rows)
        if not candidates:
            self.candidates_layout.addWidget(EmptyState(
                "No Skill candidates yet. These appear once a similar multi-step "
                "workflow shows up at least 3 times in your history."
            ))
        else:
            for c in candidates:
                # An existing DETECTED Skill always takes precedence over
                # suggesting a new one (spec Feature 5).
                probe_text = " ".join(c.get("examples", [])) or c["name"]
                match = match_skills(probe_text, skills) if skills else None
                if match:
                    card = CandidateCard(c, "🔧")
                    note = QLabel(f"✓ Existing Skill '{match.name}' already covers this "
                                  f"— use it instead of creating a new one.")
                    note.setWordWrap(True)
                    note.setStyleSheet(f"color: {theme.GOOD}; font-size: 11.5px; padding: 4px 16px;")
                    self.candidates_layout.addWidget(card)
                    self.candidates_layout.addWidget(note)
                else:
                    self.candidates_layout.addWidget(CandidateCard(
                        c, "🔧", on_create=self._on_create_skill, create_label="Create Skill",
                    ))

    def _on_create_skill(self, candidate: dict) -> None:
        self.controller.start_skill_draft_from_candidate(candidate)
