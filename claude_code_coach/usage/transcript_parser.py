"""Reads real token usage directly out of Claude Code's own local session
transcripts (~/.claude/projects/<project>/<session>.jsonl) — the same JSONL
files Claude Code itself writes for every session, on every platform it
supports. Nothing here is fabricated or estimated: every field pulled is a
real number Claude Code already recorded for its own purposes.

This is a read-only, best-effort scanner: a missing directory, an empty or
mid-write file, or a malformed line is skipped, never a crash — the same
defensive posture as runtime/event_parser.py for hook payloads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UsageRecord:
    timestamp: str  # ISO 8601, as Claude Code wrote it
    model: str
    session_id: str
    project_dir: str  # the raw ~/.claude/projects/<this> folder name
    cwd: str  # real working directory Claude Code recorded for this message
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_5m_tokens: int
    cache_write_1h_tokens: int

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens + self.output_tokens + self.cache_read_tokens
            + self.cache_write_5m_tokens + self.cache_write_1h_tokens
        )


def default_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def _parse_line(line: str, project_dir_name: str) -> UsageRecord | None:
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None

    message = obj.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None

    model = message.get("model")
    if not isinstance(model, str) or not model:
        return None

    cache_creation = usage.get("cache_creation")
    if isinstance(cache_creation, dict):
        write_5m = cache_creation.get("ephemeral_5m_input_tokens", 0)
        write_1h = cache_creation.get("ephemeral_1h_input_tokens", 0)
    else:
        # Older/simpler transcript shape: one undifferentiated cache-creation
        # count with no 5m/1h split. Treated as 5-minute (Claude Code's
        # default TTL) rather than guessed as 1-hour, since 5-minute caching
        # is the default and 1-hour is an opt-in feature.
        write_5m = usage.get("cache_creation_input_tokens", 0)
        write_1h = 0

    def _int(value) -> int:
        return value if isinstance(value, int) else 0

    return UsageRecord(
        timestamp=obj.get("timestamp") if isinstance(obj.get("timestamp"), str) else "",
        model=model,
        session_id=obj.get("sessionId") if isinstance(obj.get("sessionId"), str) else "",
        project_dir=project_dir_name,
        cwd=obj.get("cwd") if isinstance(obj.get("cwd"), str) else "",
        input_tokens=_int(usage.get("input_tokens")),
        output_tokens=_int(usage.get("output_tokens")),
        cache_read_tokens=_int(usage.get("cache_read_input_tokens")),
        cache_write_5m_tokens=_int(write_5m),
        cache_write_1h_tokens=_int(write_1h),
    )


def scan_transcript_file(path: Path) -> list[UsageRecord]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    project_dir_name = path.parent.name
    records = []
    for line in text.splitlines():
        record = _parse_line(line, project_dir_name)
        if record is not None:
            records.append(record)
    return records


def scan_all_transcripts(projects_dir: Path | None = None) -> list[UsageRecord]:
    """Every *.jsonl under every project folder — i.e. every Claude Code
    session ever run on this machine, matching the "all projects" scope.
    Each file/line failure is isolated; one bad file never drops the rest.
    """
    root = projects_dir or default_projects_dir()
    if not root.is_dir():
        return []

    records: list[UsageRecord] = []
    try:
        project_dirs = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return []

    for project_dir in project_dirs:
        try:
            transcript_files = sorted(project_dir.glob("*.jsonl"))
        except OSError:
            continue
        for transcript_file in transcript_files:
            records.extend(scan_transcript_file(transcript_file))

    return records
