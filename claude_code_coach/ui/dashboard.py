from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from claude_code_coach.analytics import (
    agent_candidates,
    claude_md_candidates,
    context_stats,
    habit_trends,
    skill_candidates,
    today_stats,
)
from claude_code_coach.runtime.models import ConnectionState

from . import theme
from .widgets import Badge, EmptyState, Panel, PercentBar, SectionHeader, StatCard, backend_mode_label, page_header

_RUNTIME_STATE_TEXT = {
    ConnectionState.LIVE: ("● Connected", theme.GOOD),
    ConnectionState.CONNECTED: ("● Connected (idle)", theme.WARN),
    ConnectionState.CONFIGURED: ("○ Configured, no events yet", theme.INFO),
    ConnectionState.NOT_CONFIGURED: ("○ Not connected", theme.TEXT_MUTED),
    ConnectionState.UNAVAILABLE: ("○ Not connected", theme.TEXT_MUTED),
    ConnectionState.UNKNOWN: ("○ Unknown", theme.TEXT_MUTED),
}


# Top-level "home" view: summarizes recommendations, today's coaching stats,
# habit trends, opportunities, and runtime connection status in one place.
class Dashboard(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header(
            "Dashboard Test",
            "Your local Claude Code workflow habits — not an official Anthropic metric.",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setSpacing(18)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # -- Recommendations (V5 Feature 12: at most 3, actionable) ---------------
        self._content_layout.addWidget(SectionHeader("RECOMMENDATIONS"))
        self.recs_panel = Panel()
        self.recs_layout = QVBoxLayout(self.recs_panel)
        self.recs_layout.setContentsMargins(18, 16, 18, 16)
        self.recs_layout.setSpacing(6)
        self._content_layout.addWidget(self.recs_panel)

        # -- Today's Coaching --------------------------------------------------
        self._content_layout.addWidget(SectionHeader("TODAY'S COACHING"))
        self.today_cards = QHBoxLayout()
        self.today_cards.setSpacing(14)
        self._content_layout.addLayout(self.today_cards)

        # -- Habit Trends -----------------------------------------------------
        self._content_layout.addWidget(SectionHeader("HABIT TRENDS"))
        self.habits_panel = Panel()
        self.habits_layout = QVBoxLayout(self.habits_panel)
        self.habits_layout.setContentsMargins(18, 16, 18, 16)
        self.habits_layout.setSpacing(12)
        self._content_layout.addWidget(self.habits_panel)

        # -- Opportunities ------------------------------------------------------
        self._content_layout.addWidget(SectionHeader("OPPORTUNITIES"))
        self.opps_panel = Panel()
        self.opps_layout = QVBoxLayout(self.opps_panel)
        self.opps_layout.setContentsMargins(18, 16, 18, 16)
        self._content_layout.addWidget(self.opps_panel)

        # -- Runtime --------------------------------------------------------------
        self._content_layout.addWidget(SectionHeader("RUNTIME"))
        self.runtime_panel = Panel()
        self.runtime_layout = QVBoxLayout(self.runtime_panel)
        self.runtime_layout.setContentsMargins(18, 16, 18, 16)
        self.runtime_layout.setSpacing(6)
        self._content_layout.addWidget(self.runtime_panel)

        self._content_layout.addStretch()

        self.refresh()

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def refresh(self) -> None:
        rows = self.controller.history()

        self._clear_layout(self.recs_layout)
        recs = self.controller.top_recommendations(limit=3)
        if not recs:
            self.recs_layout.addWidget(EmptyState(
                "No recommendations yet — analyze a prompt or enable Runtime coaching."
            ))
        else:
            for text in recs:
                label = QLabel(text)
                label.setWordWrap(True)
                label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12.5px; padding: 2px 0;")
                self.recs_layout.addWidget(label)

        self._clear_layout(self.today_cards)
        stats = today_stats(rows)
        self.today_cards.addWidget(StatCard(
            "PROMPTS TODAY", str(stats["count"]), "analyzed locally"
        ))
        self.today_cards.addWidget(StatCard(
            "AVG SCORE", f"{stats['avg_score']}/100" if stats["count"] else "--",
            "context efficiency score"
        ))
        self.today_cards.addWidget(StatCard(
            "GOOD HABITS", str(stats["good_count"]), "detected today"
        ))
        self.today_cards.addWidget(StatCard(
            "WARNINGS", str(stats["warning_count"]), "detected today"
        ))

        self._clear_layout(self.habits_layout)
        trends = habit_trends(rows)
        if not rows:
            self.habits_layout.addWidget(
                EmptyState("Analyze a prompt in Prompt Inspector to start building habit data.")
            )
        else:
            grid = QGridLayout()
            grid.setHorizontalSpacing(24)
            grid.setVerticalSpacing(10)
            for i, trend in enumerate(trends):
                bar = PercentBar(trend["label"])
                bar.set_percent(trend["pct"], trend["sample_size"])
                grid.addWidget(bar, i // 2, i % 2)
            self.habits_layout.addLayout(grid)

        self._clear_layout(self.opps_layout)
        skills = skill_candidates(rows)
        agents = agent_candidates(rows)
        claude_md = claude_md_candidates(rows)
        ctx = context_stats(rows)

        if not rows:
            self.opps_layout.addWidget(
                EmptyState("No opportunities detected yet — this needs some prompt history.")
            )
        else:
            lines = [
                f"🔧  {len(skills)} Skill candidate(s)",
                f"🤖  {len(agents)} Agent candidate(s)",
                f"📝  {len(claude_md)} Persistent-rule (CLAUDE.md) candidate(s)",
            ]
            if ctx["suggest_compaction"]:
                lines.append("🧠  Context management may help — see the Context page.")
            for text in lines:
                label = QLabel(text)
                # UI stabilization pass (docs/UI_STABILIZATION_AUDIT.md,
                # Issue 16): these lines are dynamically generated and can
                # grow long (candidate counts, context note) — without
                # word-wrap they forced an oversized page minimum width.
                label.setWordWrap(True)
                label.setStyleSheet(f"padding: 4px 0; color: {theme.TEXT_PRIMARY};")
                self.opps_layout.addWidget(label)

        self._clear_layout(self.runtime_layout)
        self.controller.poll_runtime()
        status = self.controller.runtime_status()
        state_text, state_color = _RUNTIME_STATE_TEXT.get(
            status.state, ("○ Unknown", theme.TEXT_MUTED)
        )
        # A left-border status accent (Executive Dashboard pattern) so the
        # runtime panel is scannable at a glance without reading its text —
        # matches the same color already used for the state label below.
        self.runtime_panel.setStyleSheet(theme.status_border_style(state_color))
        header_row = QHBoxLayout()
        state_label = QLabel(state_text)
        state_label.setStyleSheet(f"font-weight: 700; color: {state_color};")
        header_row.addWidget(state_label)
        header_row.addStretch()
        self.runtime_layout.addLayout(header_row)

        if status.current_session:
            s = status.current_session
            summary = QLabel(
                f"Current session: {s.prompts} prompt(s), {s.tool_calls} tool call(s), "
                f"{s.reads} read(s), {s.edits} edit(s)"
            )
            summary.setWordWrap(True)
            summary.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")
            self.runtime_layout.addWidget(summary)
            if status.signals:
                sig_text = QLabel(
                    "Coach: " + "; ".join(f"⚠ {sig.message}" for sig in status.signals[:2])
                )
                sig_text.setWordWrap(True)
                sig_text.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11.5px;")
                self.runtime_layout.addWidget(sig_text)
        else:
            note = QLabel("Runtime coaching unavailable — install hooks on the Runtime page.")
            note.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
            self.runtime_layout.addWidget(note)

        # Phase 4C, Step 5/11 ("first migration slice"): one small,
        # additive readout of which Coach backend this app is currently
        # using — genuinely sourced via a real HTTP call
        # (controller.coach_backend_summary() -> backend_client.health())
        # when a service is reachable, proving the Desktop can act as an
        # HTTP client of the standalone service. Everything above this
        # (recommendations, stats, habit trends, opportunities, and the
        # connection-state line itself) is untouched — still the existing
        # direct coach.db/analyzer reads, which already reflect a
        # standalone service's writes for free since both share one
        # database file. See docs/DESKTOP_SERVICE_MIGRATION.md.
        backend = self.controller.coach_backend_summary()
        backend_color = theme.GOOD if backend["reachable"] else theme.TEXT_MUTED
        mode_text = backend_mode_label(backend["mode"])
        backend_label = QLabel(f"Coach Service: {mode_text}\n{backend['detail']}")
        backend_label.setWordWrap(True)
        backend_label.setStyleSheet(f"color: {backend_color}; font-size: 11px; margin-top: 4px;")
        self.runtime_layout.addWidget(backend_label)
