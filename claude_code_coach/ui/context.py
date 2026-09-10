from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from claude_code_coach.analytics import claude_md_candidates, context_stats

from . import theme
from .widgets import CandidateCard, EmptyState, Panel, SectionHeader, StatCard, page_header


class Context(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header(
            "Context",
            "Local prompt-habit signals only — not a measurement of Claude's "
            "actual context window or token usage.",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(18)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.content_layout.addWidget(SectionHeader("CONTEXT HEALTH (CURRENT RUNTIME SESSION)"))
        self.health_panel = Panel()
        self.health_layout = QVBoxLayout(self.health_panel)
        self.health_layout.setContentsMargins(18, 16, 18, 16)
        self.health_layout.setSpacing(6)
        self.content_layout.addWidget(self.health_panel)

        self.content_layout.addWidget(SectionHeader("SESSION-AGNOSTIC STATS"))
        self.stat_cards = QHBoxLayout()
        self.stat_cards.setSpacing(14)
        self.content_layout.addLayout(self.stat_cards)

        self.content_layout.addWidget(SectionHeader("GUIDANCE"))
        self.guidance_panel = Panel()
        self.guidance_layout = QVBoxLayout(self.guidance_panel)
        self.guidance_layout.setContentsMargins(18, 16, 18, 16)
        self.content_layout.addWidget(self.guidance_panel)

        self.content_layout.addWidget(SectionHeader("PERSISTENT-RULE (CLAUDE.MD) CANDIDATES"))
        self.rules_layout = QVBoxLayout()
        self.rules_layout.setSpacing(10)
        self.content_layout.addLayout(self.rules_layout)

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
        rows = self.controller.history()
        stats = context_stats(rows)

        self._clear(self.health_layout)
        if not self.controller.runtime_enabled:
            self.health_layout.addWidget(EmptyState(
                "Runtime coaching is off. Context Health needs a live runtime session — "
                "prompt-history stats below still work without it."
            ))
        else:
            status = self.controller.runtime_status()
            if not status.current_session:
                self.health_layout.addWidget(EmptyState(
                    "No active runtime session yet — see the Sessions page to install hooks."
                ))
            else:
                health = status.context_health
                title = QLabel(f"{health}%" if health is not None else "n/a")
                title.setStyleSheet(f"font-size: 28px; font-weight: 800; color: {theme.rating_color('GOOD') if (health or 0) >= 70 else theme.rating_color('NEEDS IMPROVEMENT') if (health or 0) >= 40 else theme.rating_color('POOR')};")
                self.health_layout.addWidget(title)
                for sig in status.signals:
                    if sig.kind in ("context_noisy", "context_coherent"):
                        icon = "⚠" if sig.kind == "context_noisy" else "✓"
                        note = QLabel(f"{icon} {sig.message}")
                        note.setWordWrap(True)
                        note.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")
                        self.health_layout.addWidget(note)
                        if sig.try_instead:
                            tip = QLabel(f"Recommendation: {sig.try_instead}")
                            tip.setWordWrap(True)
                            tip.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11.5px;")
                            self.health_layout.addWidget(tip)
                disclaimer = QLabel("Local coaching heuristic — not an official Anthropic metric.")
                disclaimer.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px;")
                self.health_layout.addWidget(disclaimer)

        self._clear(self.stat_cards)
        self.stat_cards.addWidget(StatCard(
            "AVG PROMPT LENGTH", f"{stats['avg_prompt_words']} words", "across history"
        ))
        self.stat_cards.addWidget(StatCard(
            "AVG SCORE", f"{stats['avg_score']}/100" if stats["total"] else "--",
            "context efficiency score"
        ))
        self.stat_cards.addWidget(StatCard(
            "BROAD-TASK FREQUENCY", f"{stats['broad_task_pct']}%", "of prompts flagged broad"
        ))
        self.stat_cards.addWidget(StatCard(
            "REPEATED INSTRUCTIONS", f"{stats['repeated_instruction_pct']}%",
            "prompts in a repeated cluster"
        ))

        self._clear(self.guidance_layout)
        if not rows:
            self.guidance_layout.addWidget(EmptyState("No history yet — analyze some prompts first."))
        else:
            lines = [f"🧠  {stats['context_warning_count']} prompt(s) referenced a large amount of prior discussion."]
            if stats["suggest_compaction"]:
                lines.append(
                    "→  Consider narrowing scope, searching first, running /compact, "
                    "or starting a fresh session for unrelated work."
                )
            else:
                lines.append("→  No strong signal that context management is needed right now.")
            for text in lines:
                label = QLabel(text)
                label.setWordWrap(True)
                label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; padding: 3px 0;")
                self.guidance_layout.addWidget(label)

        while self.rules_layout.count():
            item = self.rules_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        candidates = claude_md_candidates(rows)
        if not candidates:
            self.rules_layout.addWidget(EmptyState(
                "No persistent project-rule candidates detected yet."
            ))
        else:
            for c in candidates:
                self.rules_layout.addWidget(CandidateCard(c, "📝"))
