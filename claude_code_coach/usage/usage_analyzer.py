"""Aggregates real UsageRecords (transcript_parser.py) into the summaries the
Usage page displays. Every number here is either a direct sum of real,
observed token counts, or a cost estimate derived from them via pricing.py's
published-pricing table — nothing is invented.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .pricing import estimate_cost_usd
from .transcript_parser import UsageRecord, scan_all_transcripts


@dataclass
class TokenTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    cost_usd: float = 0.0
    unpriced_tokens: int = 0  # real tokens whose model has no entry in pricing.py
    record_count: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens + self.output_tokens + self.cache_read_tokens
            + self.cache_write_5m_tokens + self.cache_write_1h_tokens
        )

    def add(self, record: UsageRecord) -> None:
        self.input_tokens += record.input_tokens
        self.output_tokens += record.output_tokens
        self.cache_read_tokens += record.cache_read_tokens
        self.cache_write_5m_tokens += record.cache_write_5m_tokens
        self.cache_write_1h_tokens += record.cache_write_1h_tokens
        self.record_count += 1

        cost = estimate_cost_usd(
            record.model,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            cache_read_tokens=record.cache_read_tokens,
            cache_write_5m_tokens=record.cache_write_5m_tokens,
            cache_write_1h_tokens=record.cache_write_1h_tokens,
        )
        if cost is None:
            self.unpriced_tokens += record.total_tokens
        else:
            self.cost_usd += cost


@dataclass
class UsageSummary:
    all_time: TokenTotals = field(default_factory=TokenTotals)
    today: TokenTotals = field(default_factory=TokenTotals)
    by_project: dict[str, TokenTotals] = field(default_factory=dict)
    by_model: dict[str, TokenTotals] = field(default_factory=dict)
    session_count: int = 0
    scanned_at: str = ""


def build_usage_summary(records: list[UsageRecord] | None = None) -> UsageSummary:
    if records is None:
        records = scan_all_transcripts()

    summary = UsageSummary(scanned_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    by_project: dict[str, TokenTotals] = defaultdict(TokenTotals)
    by_model: dict[str, TokenTotals] = defaultdict(TokenTotals)
    # Claude Code's own ~/.claude/projects/<folder> name is one-per-project-
    # root and stable; the per-message `cwd` it also records can vary by
    # subdirectory (and drive-letter casing) within the same project, so
    # grouping by raw cwd fragments one real project into many rows. Group
    # by project_dir instead, and label each group with whichever real cwd
    # was seen most often in it — still real, observed text, just chosen
    # for readability rather than used as the grouping key.
    cwd_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    sessions_seen: set[str] = set()
    today_str = datetime.now(timezone.utc).date().isoformat()

    for record in records:
        summary.all_time.add(record)
        by_project[record.project_dir].add(record)
        by_model[record.model].add(record)
        if record.cwd:
            cwd_counts[record.project_dir][record.cwd] += 1
        if record.session_id:
            sessions_seen.add(record.session_id)

        # Claude Code timestamps are UTC ISO 8601 ("...Z"); comparing the
        # date portion directly avoids a timezone-conversion dependency.
        if record.timestamp.startswith(today_str):
            summary.today.add(record)

    labeled_by_project: dict[str, TokenTotals] = {}
    for project_dir, totals in by_project.items():
        counts = cwd_counts.get(project_dir)
        label = max(counts, key=counts.get) if counts else project_dir
        labeled_by_project[label] = totals

    summary.by_project = labeled_by_project
    summary.by_model = dict(by_model)
    summary.session_count = len(sessions_seen)
    return summary
