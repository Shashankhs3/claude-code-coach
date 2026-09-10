from __future__ import annotations

from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from claude_code_coach.analytics import agent_candidates
from claude_code_coach.integration.environment_matching import match_agents

from . import theme
from .environment import DetectedItemCard
from .widgets import CandidateCard, EmptyState, SectionHeader, page_header


class Agents(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header(
            "Agents",
            "Real Agents detected in your Claude Code environment, plus independent "
            "investigations in your prompt history that may be worth delegating to one.",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(12)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # -- Existing (DETECTED) Agents -------------------------------------------
        self.content_layout.addWidget(SectionHeader("EXISTING AGENTS (DETECTED)"))
        self.existing_layout = QVBoxLayout()
        self.existing_layout.setSpacing(10)
        self.content_layout.addLayout(self.existing_layout)

        # -- Agent candidates (INFERRED from history) -------------------------------
        self.content_layout.addWidget(SectionHeader("AGENT CANDIDATES (INFERRED)"))
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
        agents = snapshot.agents if snapshot else []
        if not agents:
            self.existing_layout.addWidget(EmptyState(
                "No Agents detected in your Claude Code environment yet. "
                "Scan on the Environment page after selecting a project folder."
            ))
        else:
            for agent in agents:
                source = agent.source.value if hasattr(agent.source, "value") else str(agent.source)
                self.existing_layout.addWidget(
                    DetectedItemCard(agent.name, agent.description, source, agent.modified)
                )

        self._clear(self.candidates_layout)
        rows = self.controller.history()
        candidates = agent_candidates(rows)
        if not candidates:
            self.candidates_layout.addWidget(EmptyState(
                "No Agent candidates yet. These appear when a prompt looks like a "
                "substantial, independent investigation across multiple areas."
            ))
        else:
            for c in candidates:
                probe_text = " ".join(c.get("examples", [])) or c["name"]
                match = match_agents(probe_text, agents) if agents else None
                if match:
                    card = CandidateCard(c, "🤖")
                    note = QLabel(f"✓ Existing Agent '{match.name}' may already cover this "
                                  f"— consider it before creating a new one.")
                    note.setWordWrap(True)
                    note.setStyleSheet(f"color: {theme.GOOD}; font-size: 11.5px; padding: 4px 16px;")
                    self.candidates_layout.addWidget(card)
                    self.candidates_layout.addWidget(note)
                else:
                    self.candidates_layout.addWidget(CandidateCard(
                        c, "🤖", on_create=self._on_create_agent, create_label="Create Agent",
                    ))

    def _on_create_agent(self, candidate: dict) -> None:
        self.controller.start_agent_draft_from_candidate(candidate)
