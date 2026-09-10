"""Turns a raw Claude Code hook JSON payload into a normalized RuntimeEvent.

Privacy design (spec section 22): prompt/response *text* is never stored by
default — only derived, non-reversible signals (word counts, a token set for
similarity clustering, and the existing V3 analyzer's task classification).
Raw text is stored only if the user has explicitly opted into content
collection. Anything that IS captured as text (a Bash command, a file path)
is passed through the same secret-redaction used by the V3.1 environment
scanner.
"""

from __future__ import annotations

from datetime import datetime

from ..analytics.patterns import tokenize
from ..analyzer import analyze_prompt
from ..providers.redaction import redact_secrets
from .models import RuntimeEvent, RuntimeEventType

_MAX_STORED_TOKENS = 40


def parse_hook_payload(raw: dict, *, collect_content: bool = False) -> RuntimeEvent:
    event_type = RuntimeEventType.from_hook_name(str(raw.get("hook_event_name", "")))
    session_id = str(raw.get("session_id") or "unknown")
    received_at = datetime.now().isoformat(timespec="seconds")

    tool_name = raw.get("tool_name")
    metadata: dict = {}
    content: str | None = None

    if event_type == RuntimeEventType.USER_PROMPT_SUBMIT:
        prompt = str(raw.get("prompt", ""))
        analysis = analyze_prompt(prompt)
        metadata.update({
            "word_count": len(prompt.split()),
            "tokens": sorted(tokenize(prompt))[:_MAX_STORED_TOKENS],
            "task_type": analysis.task_type,
            "scope_status": analysis.dimension_status("scope"),
            "goal_status": analysis.dimension_status("goal"),
            "breadth_level": analysis.breadth_level,
            "vague_goal": analysis.vague_goal,
        })
        if collect_content:
            content = redact_secrets(prompt)

    elif event_type in (RuntimeEventType.PRE_TOOL_USE, RuntimeEventType.POST_TOOL_USE):
        tool_input = raw.get("tool_input") or {}
        if isinstance(tool_input, dict):
            if "file_path" in tool_input:
                metadata["file_path"] = str(tool_input.get("file_path", ""))
            if "pattern" in tool_input:
                metadata["pattern"] = redact_secrets(str(tool_input.get("pattern", "")))[:200]
            if "command" in tool_input:
                metadata["command"] = redact_secrets(str(tool_input.get("command", "")))[:200]
        if event_type == RuntimeEventType.POST_TOOL_USE and collect_content:
            response = raw.get("tool_response")
            if isinstance(response, str):
                content = redact_secrets(response)[:2000]

    elif event_type == RuntimeEventType.STOP:
        message = str(raw.get("last_assistant_message", ""))
        metadata["response_word_count"] = len(message.split())
        if collect_content:
            content = redact_secrets(message)

    elif event_type == RuntimeEventType.SUBAGENT_STOP:
        metadata["agent_type"] = raw.get("agent_type", "")
        metadata["agent_id"] = raw.get("agent_id", "")

    elif event_type == RuntimeEventType.PRE_COMPACT:
        metadata["trigger"] = raw.get("trigger", raw.get("matcher", ""))

    elif event_type == RuntimeEventType.NOTIFICATION:
        metadata["notification_type"] = raw.get("notification_type", "")

    elif event_type == RuntimeEventType.PERMISSION_REQUEST:
        pass  # tool_name alone is enough signal here

    elif event_type == RuntimeEventType.SESSION_START:
        metadata["cwd"] = raw.get("cwd", "")

    return RuntimeEvent(
        id=None,
        received_at=received_at,
        session_id=session_id,
        event_type=event_type,
        tool_name=tool_name,
        metadata=metadata,
        content=content,
    )
