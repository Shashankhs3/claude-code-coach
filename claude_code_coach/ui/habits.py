from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from claude_code_coach.analytics import habit_trends
from claude_code_coach.analytics.habits import all_time_opportunity_counts

from .widgets import EmptyState, Panel, PercentBar, SectionHeader, StatCard, page_header


class Habits(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header(
            "Habits",
            "How your prompting habits trend across every prompt you've analyzed.",
        ))

        outer.addWidget(SectionHeader("DIMENSION TRENDS"))
        self.trend_panel = Panel()
        self.trend_layout = QVBoxLayout(self.trend_panel)
        self.trend_layout.setContentsMargins(18, 16, 18, 16)
        outer.addWidget(self.trend_panel)

        outer.addWidget(SectionHeader("OPPORTUNITY SIGNALS (ALL TIME)"))
        self.opp_cards = QHBoxLayout()
        outer.addLayout(self.opp_cards)

        outer.addStretch()

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

        self._clear(self.trend_layout)
        if not rows:
            self.trend_layout.addWidget(EmptyState("No data yet. Analyze some prompts first."))
        else:
            grid = QGridLayout()
            grid.setHorizontalSpacing(28)
            grid.setVerticalSpacing(12)
            for i, trend in enumerate(habit_trends(rows)):
                bar = PercentBar(trend["label"])
                bar.set_percent(trend["pct"], trend["sample_size"])
                grid.addWidget(bar, i // 2, i % 2)
            self.trend_layout.addLayout(grid)

        self._clear(self.opp_cards)
        counts = all_time_opportunity_counts(rows)
        self.opp_cards.addWidget(StatCard("SKILL SIGNALS", str(counts["skill"]), "prompts flagged"))
        self.opp_cards.addWidget(StatCard("AGENT SIGNALS", str(counts["agent"]), "prompts flagged"))
        self.opp_cards.addWidget(StatCard("CLAUDE.MD SIGNALS", str(counts["claude_md"]), "prompts flagged"))
        self.opp_cards.addWidget(StatCard("CONTEXT SIGNALS", str(counts["context"]), "prompts flagged"))
