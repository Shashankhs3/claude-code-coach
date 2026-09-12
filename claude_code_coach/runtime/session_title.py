"""Deterministic, non-AI Session Title generation.

No LLM/API call happens anywhere in this module — every transform below is a
fixed regex/string rule, chosen so the result is always explainable by
pointing at the rule that produced it. See docs/STANDALONE_SERVICE.md /
runtime/event_parser.py for why the input this module gets is already
privacy-constrained before it ever reaches here.

Priority (spec: no fabrication, real information only):
  1. The session's first UserPromptSubmit event's real prompt *text* — only
     present at all when the user has opted into `runtime_collect_content`
     (see event_parser.py). This is the only tier that can produce a title
     resembling actual task wording.
  2. That same first prompt's already-computed `task_type` classification
     (event_parser.py runs the real V3 analyzer on the real prompt before
     discarding the text) — real, non-fabricated, just coarser-grained.
  3. `FALLBACK_TITLE`, when no UserPromptSubmit event has been observed yet.

A title is derived once from the *first* prompt and is therefore stable for
the life of the session (spec section 12) — it is never recomputed from a
later prompt, so it never silently renames itself mid-session.
"""

from __future__ import annotations

import re

from ..providers.redaction import redact_secrets
from .models import RuntimeEvent, RuntimeEventType

FALLBACK_TITLE = "Untitled session"

MAX_TITLE_WORDS = 8
MAX_TITLE_CHARS = 60

# Politeness/framing wrappers that carry no task information. Stripped from
# the *start* of the clause only, repeatedly (a fixed number of passes) so
# stacked framing ("Could you please help me understand...") reduces to its
# actual content ("understand...") without an unbounded loop on adversarial
# input.
_BOILERPLATE_PREFIXES = [
    re.compile(r"^(?:hi|hey|hello)[,!]?\s+", re.IGNORECASE),
    re.compile(r"^please\s+", re.IGNORECASE),
    re.compile(r"^(?:can|could|would)\s+you\s+(?:please\s+)?", re.IGNORECASE),
    re.compile(r"^i(?:'d| would| want| need)\s+(?:you\s+)?to\s+", re.IGNORECASE),
    re.compile(r"^help me\s+(?:to\s+)?", re.IGNORECASE),
    re.compile(r"^i'?m trying to\s+", re.IGNORECASE),
    re.compile(r"^i am trying to\s+", re.IGNORECASE),
    re.compile(r"^let'?s\s+", re.IGNORECASE),
    re.compile(r"^let us\s+", re.IGNORECASE),
]
_MAX_PREFIX_PASSES = 3

_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]*`")
_URL = re.compile(r"https?://\S+")
_LIST_MARKER = re.compile(r"^(?:[-*•]|\d+[.)])\s+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s")
_TRAILING_PUNCT = re.compile(r"[\s.,;:!?]+$")

# Below this fraction of alphanumeric characters, the leftover clause is
# more likely a stray code/path fragment than readable text — reject it
# rather than surface something unreadable as a "title".
_MIN_ALNUM_RATIO = 0.4


def title_for_session(events: list[RuntimeEvent]) -> str:
    """Derive a Session Title from `events` (ascending, as read from the
    database). Looks only at the *first* UserPromptSubmit event so the
    result stays stable across the session's lifetime."""
    first_prompt = next(
        (e for e in events if e.event_type == RuntimeEventType.USER_PROMPT_SUBMIT), None
    )
    if first_prompt is None:
        return FALLBACK_TITLE

    if first_prompt.content:
        from_text = _title_from_prompt_text(first_prompt.content)
        if from_text:
            return from_text

    task_type = (first_prompt.metadata or {}).get("task_type")
    if task_type:
        from_task_type = _title_from_task_type(str(task_type))
        if from_task_type:
            return from_task_type

    return FALLBACK_TITLE


def _title_from_task_type(task_type: str) -> str | None:
    from ..analyzer.task_classifier import TaskType

    try:
        label = TaskType(task_type).label
    except ValueError:
        return None
    return f"{label} session"


def _title_from_prompt_text(text: str) -> str | None:
    text = redact_secrets(text)
    text = _CODE_FENCE.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    text = _URL.sub(" ", text)

    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if not line:
        return None
    line = _LIST_MARKER.sub("", line)

    clause = _SENTENCE_SPLIT.split(line, maxsplit=1)[0]
    clause = " ".join(clause.split())  # collapse internal whitespace

    for _ in range(_MAX_PREFIX_PASSES):
        stripped = clause
        for pattern in _BOILERPLATE_PREFIXES:
            stripped = pattern.sub("", stripped)
        if stripped == clause:
            break
        clause = stripped

    clause = _TRAILING_PUNCT.sub("", clause).strip()
    if not clause:
        return None

    words = clause.split()
    if len(words) > MAX_TITLE_WORDS:
        clause = " ".join(words[:MAX_TITLE_WORDS])
    if len(clause) > MAX_TITLE_CHARS:
        clause = clause[:MAX_TITLE_CHARS].rsplit(" ", 1)[0]
    clause = _TRAILING_PUNCT.sub("", clause).strip()
    if not clause:
        return None

    alnum = sum(1 for c in clause if c.isalnum())
    if alnum == 0 or alnum / len(clause) < _MIN_ALNUM_RATIO:
        return None
    if not any(c.isalpha() for c in clause):
        return None

    return clause[0].upper() + clause[1:]
