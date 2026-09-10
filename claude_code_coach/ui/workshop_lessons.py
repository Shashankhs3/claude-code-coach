"""Expanded (why/try) educational text for Workshop Mode (spec Feature 10).

Keyed by the same dimension keys as analyzer.models / opportunity kinds as
analyzer.opportunities, so the Inspector can look these up directly instead
of guessing from free-text warning strings.
"""

from __future__ import annotations

DIMENSION_LESSONS: dict[str, tuple[str, str]] = {
    "goal": (
        "Claude works best from a concrete target or problem, not a vague "
        "instruction — 'fix it' gives no starting point to investigate from.",
        "State what's broken or what outcome you want, in concrete terms.",
    ),
    "scope": (
        "Claude can investigate broad areas when appropriate, but for a "
        "narrow task, a defined starting point reduces unnecessary exploration.",
        "Name the affected file, directory, or component.",
    ),
    "investigation": (
        "Reading broadly before narrowing pulls unrelated code into context "
        "that a targeted search would have skipped entirely.",
        "Ask Claude to search/locate the relevant code first, then read only "
        "what matches.",
    ),
    "constraints": (
        "Without constraints, Claude has to guess what's safe to touch and "
        "what conventions to follow.",
        "Say what must not change, or what conventions to preserve.",
    ),
    "done": (
        "Without a definition of done, it's unclear when the task is actually "
        "finished or how to verify it.",
        "Add a 'Done when...' condition — e.g. tests pass, behavior confirmed.",
    ),
    "output": (
        "An unconstrained response can be longer or less focused than you need.",
        "Say what you want back — a summary, a table, a list of files.",
    ),
}

OPPORTUNITY_LESSONS: dict[str, tuple[str, str]] = {
    "skill": (
        "A Skill packages a repeatable, multi-step workflow so it's performed "
        "consistently instead of re-explained every time.",
        "If this workflow repeats, consider creating or using a Skill for it.",
    ),
    "agent": (
        "An Agent is a delegated specialist for independent, substantial "
        "investigation — useful when work spans several unrelated areas.",
        "Consider delegating this kind of investigation to an Agent.",
    ),
    "claude_md": (
        "Persistent project rules belong in CLAUDE.md once, not repeated in "
        "every prompt.",
        "Move durable instructions into CLAUDE.md instead of restating them.",
    ),
    "context": (
        "A session that's accumulated a lot of unrelated prior discussion can "
        "dilute focus on the current task.",
        "Consider narrowing scope, searching first, or starting fresh.",
    ),
    "search_first": (
        "Searching/locating first keeps context smaller than reading broadly "
        "and hoping to find the right file.",
        "Try a search/grep step before reading many files.",
    ),
}
