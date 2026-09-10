"""Usage page: real token counts read directly out of Claude Code's own
local session transcripts (see claude_code_coach/usage/), with an
*estimated* cost on top computed from Anthropic's published per-model
pricing. Token counts are real, observed numbers — never fabricated. Cost
is explicitly labeled as an estimate, not a bill.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from claude_code_coach.usage import PRICING_AS_OF, PRICING_SOURCE_URL, TokenTotals

from . import theme
from .widgets import EmptyState, Panel, SectionHeader, StatCard, page_header


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _fmt_usd(amount: float) -> str:
    return f"${amount:,.2f}"


def _short_label(text: str, max_len: int = 58) -> str:
    if len(text) <= max_len:
        return text
    return "…" + text[-(max_len - 1):]


class UsageRow(Panel):
    def __init__(self, label: str, totals: TokenTotals, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)

        name = QLabel(_short_label(label))
        name.setToolTip(label)
        name.setStyleSheet(f"font-size: 12.5px; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(name, stretch=1)

        tokens = QLabel(f"{_fmt_int(totals.total_tokens)} tokens")
        tokens.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11.5px;")
        layout.addWidget(tokens)

        cost = QLabel(_fmt_usd(totals.cost_usd))
        cost.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; font-size: 12.5px; font-weight: 700; "
            "min-width: 70px;"
        )
        cost.setAlignment(Qt.AlignRight)
        layout.addWidget(cost)


class Usage(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header(
            "Usage",
            "Token counts are read directly from Claude Code's own local session "
            "logs — real, observed numbers, not estimates. Cost is an ESTIMATE "
            f"based on Anthropic's published pricing as of {PRICING_AS_OF} "
            f"({PRICING_SOURCE_URL}) — not an official invoice or billing record.",
        ))

        top_row = QHBoxLayout()
        self.refresh_button = QPushButton("Rescan")
        self.refresh_button.clicked.connect(self.refresh)
        self.scanned_label = QLabel("")
        self.scanned_label.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px;")
        top_row.addWidget(self.refresh_button)
        top_row.addWidget(self.scanned_label)
        top_row.addStretch()
        outer.addLayout(top_row)

        outer.addWidget(SectionHeader("ALL TIME"))
        self.stat_row = QHBoxLayout()
        outer.addLayout(self.stat_row)

        outer.addWidget(SectionHeader("TODAY"))
        self.today_row = QHBoxLayout()
        outer.addLayout(self.today_row)

        self.unpriced_label = QLabel("")
        self.unpriced_label.setWordWrap(True)
        self.unpriced_label.setStyleSheet(f"color: {theme.WARN}; font-size: 11.5px;")
        self.unpriced_label.hide()
        outer.addWidget(self.unpriced_label)

        outer.addWidget(SectionHeader("BY PROJECT"))
        self.project_layout = QVBoxLayout()
        self.project_layout.setSpacing(6)
        outer.addLayout(self.project_layout)

        outer.addWidget(SectionHeader("BY MODEL"))
        self.model_layout = QVBoxLayout()
        self.model_layout.setSpacing(6)
        outer.addLayout(self.model_layout)

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
        """Scans ~/.claude/projects/ on a background thread (env_worker.py's
        pattern, reused exactly) rather than blocking the UI thread — this
        scan only gets slower as a person's real Claude Code history grows.
        """
        if self.controller.is_usage_scanning():
            return
        self.refresh_button.setEnabled(False)
        self.scanned_label.setText("Scanning ~/.claude/projects/ …")
        self.controller.scan_usage_async(on_done=self._render, on_error=self._on_scan_error)

    def _on_scan_error(self, message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.scanned_label.setText(f"Scan failed: {message}")

    def _render(self, summary) -> None:
        self.refresh_button.setEnabled(True)
        self.scanned_label.setText(f"Last scanned: {summary.scanned_at}")

        self._clear(self.stat_row)
        all_time = summary.all_time
        if all_time.record_count == 0:
            self.stat_row.addWidget(EmptyState(
                "No Claude Code session logs found yet on this machine "
                "(~/.claude/projects/). Run a Claude Code session, then Rescan."
            ))
        else:
            self.stat_row.addWidget(StatCard(
                "TOTAL TOKENS", _fmt_int(all_time.total_tokens),
                f"{summary.session_count} session(s), {all_time.record_count} messages",
            ))
            self.stat_row.addWidget(StatCard(
                "INPUT / OUTPUT", f"{_fmt_int(all_time.input_tokens)} / {_fmt_int(all_time.output_tokens)}",
                "fresh tokens (excludes cache)",
            ))
            self.stat_row.addWidget(StatCard(
                "CACHE READ", _fmt_int(all_time.cache_read_tokens),
                "10% of input price — cheap reuse",
            ))
            self.stat_row.addWidget(StatCard(
                "CACHE WRITE", _fmt_int(all_time.cache_write_5m_tokens + all_time.cache_write_1h_tokens),
                "5-min + 1-hour cache creation",
            ))
            self.stat_row.addWidget(StatCard(
                "ESTIMATED COST", _fmt_usd(all_time.cost_usd),
                "all projects, all time",
            ))

        self._clear(self.today_row)
        today = summary.today
        self.today_row.addWidget(StatCard("TOKENS TODAY", _fmt_int(today.total_tokens)))
        self.today_row.addWidget(StatCard("ESTIMATED COST TODAY", _fmt_usd(today.cost_usd)))

        if all_time.unpriced_tokens:
            self.unpriced_label.setText(
                f"⚠ {_fmt_int(all_time.unpriced_tokens)} real tokens are from a model not in "
                "the local pricing table and are excluded from every cost estimate above "
                "(never guessed at)."
            )
            self.unpriced_label.show()
        else:
            self.unpriced_label.hide()

        self._clear(self.project_layout)
        if not summary.by_project:
            self.project_layout.addWidget(EmptyState("No project data yet."))
        else:
            ranked = sorted(summary.by_project.items(), key=lambda kv: -kv[1].total_tokens)
            for label, totals in ranked:
                self.project_layout.addWidget(UsageRow(label, totals))

        self._clear(self.model_layout)
        if not summary.by_model:
            self.model_layout.addWidget(EmptyState("No model data yet."))
        else:
            ranked = sorted(summary.by_model.items(), key=lambda kv: -kv[1].total_tokens)
            for label, totals in ranked:
                self.model_layout.addWidget(UsageRow(label, totals))
