#!/usr/bin/env python
"""The actual command Claude Code hooks invoke.

CRITICAL SAFETY PROPERTY: this script must never disrupt a real Claude Code
session. It always exits 0, never prints anything to stdout (several hook
events treat stdout as a blocking/context-injecting decision — this script
must never accidentally block or alter the user's real session), and any
internal failure is swallowed silently. It is designed to run in well under
a second: read stdin, append one line to a local file, exit.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _main() -> int:
    try:
        raw_text = sys.stdin.read()
        payload = json.loads(raw_text) if raw_text.strip() else {}
        if not isinstance(payload, dict):
            return 0

        from claude_code_coach.database import db
        from claude_code_coach.runtime.event_parser import parse_hook_payload

        collect_content = db.get_setting("runtime_collect_content", "0") == "1"
        event = parse_hook_payload(payload, collect_content=collect_content)

        events_dir = db.APP_DIR / "runtime_events"
        events_dir.mkdir(parents=True, exist_ok=True)
        session_file = events_dir / f"{_safe_filename(event.session_id)}.jsonl"

        line = json.dumps({
            "received_at": event.received_at,
            "session_id": event.session_id,
            "event_type": event.event_type.value,
            "tool_name": event.tool_name,
            "metadata": event.metadata,
            "content": event.content,
        })
        with open(session_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001 - never let this fail the user's real session
        pass
    return 0


def _safe_filename(session_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)[:120] or "unknown"


if __name__ == "__main__":
    sys.exit(_main())
