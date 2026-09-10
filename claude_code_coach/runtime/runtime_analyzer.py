"""Turns raw runtime events into coaching signals.

Every signal carries `evidence` (spec section 29) so a verdict is always
explainable, and every signal is conservative by construction — broad
reading is only flagged when the *task* also looks narrow (spec section 9);
a review/security-audit/research task legitimately reading broadly is never
penalized just for its file count (spec section 28's "large read but
justified" adversarial case).
"""

from __future__ import annotations

from pathlib import Path

from ..analytics.patterns import jaccard, tokenize
from .models import RuntimeEvent, RuntimeEventType, RuntimeSignal

SEARCH_TOOLS = {"Grep", "Glob", "WebSearch"}
READ_TOOLS = {"Read"}
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
EXEC_TOOLS = {"Bash"}

_BROAD_TASK_TYPES = {"review", "security_review", "research", "repetitive_workflow"}
_NARROW_EXCLUDED_TYPES = _BROAD_TASK_TYPES | {"information", "explanation"}

_TEST_COMMAND_WORDS = ("test", "pytest", "jest", "npm run", "go test", "mvn test",
                       "rspec", "phpunit", "dotnet test", "cargo test")

# Task-switch / compaction penalties for the context-health percentage
# (spec Features 6/8). Deliberately does NOT penalize for length alone —
# a long, single-focus session scores the same as a short one.
_TASK_SWITCH_PENALTY = 15
_COMPACTION_PENALTY = 10
_TASK_SWITCH_OVERLAP_THRESHOLD = 0.15


def _pre_tool_events(events: list[RuntimeEvent]) -> list[RuntimeEvent]:
    return [e for e in events if e.event_type == RuntimeEventType.PRE_TOOL_USE]


def search_first_signal(events: list[RuntimeEvent], prompt_context: dict | None) -> list[RuntimeSignal]:
    tool_events = _pre_tool_events(events)
    read_positions = [i for i, e in enumerate(tool_events) if e.tool_name in READ_TOOLS]
    if not read_positions:
        return []

    search_positions = [i for i, e in enumerate(tool_events) if e.tool_name in SEARCH_TOOLS]
    first_search = search_positions[0] if search_positions else None
    reads_before_search = (
        sum(1 for i in read_positions if i < first_search)
        if first_search is not None else len(read_positions)
    )

    ctx = prompt_context or {}
    task_type = ctx.get("task_type")
    justified_broad = (
        ctx.get("breadth_level", 0) >= 1 or task_type in _BROAD_TASK_TYPES
    )
    narrow_task = (
        ctx.get("scope_status") == "clear"
        and ctx.get("breadth_level", 0) == 0
        and task_type not in _NARROW_EXCLUDED_TYPES
    )

    evidence = {
        "reads_before_search": reads_before_search,
        "total_reads": len(read_positions),
        "had_search_step": first_search is not None,
        "task_type": task_type,
        "scope_status": ctx.get("scope_status"),
    }

    if justified_broad:
        if reads_before_search >= 40:
            return [RuntimeSignal(
                kind="broad_exploration", level="low",
                message="A large number of files were read, but the task looks like it "
                        "legitimately needs broad coverage.",
                what_happened=f"{reads_before_search} files were read before narrowing.",
                why_it_matters="Broad reads use more context, but a review/audit/research "
                               "task often genuinely needs this.",
                try_instead="If this exact workflow repeats often, consider a dedicated Skill "
                            "so it's consistent rather than re-explored each time.",
                evidence=evidence,
            )]
        return []

    if narrow_task and reads_before_search >= 15:
        return [RuntimeSignal(
            kind="broad_exploration", level="high",
            message="Claude appears to be reading a large portion of the repository "
                    "for a narrowly scoped task.",
            what_happened=f"{reads_before_search} files were read before any search/"
                          f"narrowing step" + ("." if first_search is not None else
                          " (no search step occurred at all)."),
            why_it_matters="Reading broadly for a narrow task pulls unnecessary code into "
                           "context and can dilute focus on the actual target.",
            try_instead="Search/grep for the relevant symbol, error, or endpoint first, "
                        "then read only the files that match.",
            evidence=evidence,
        )]

    if narrow_task and reads_before_search >= 6:
        return [RuntimeSignal(
            kind="broad_exploration", level="medium",
            message="More files were read before narrowing than this task's scope suggests.",
            what_happened=f"{reads_before_search} files read before narrowing.",
            why_it_matters="A tightly-scoped task usually needs only a handful of reads "
                           "once the relevant area is located.",
            try_instead="Try a search step first if you haven't already.",
            evidence=evidence,
        )]

    if first_search is not None and reads_before_search <= 5:
        return [RuntimeSignal(
            kind="search_first_good", level="low",
            message="Search-first workflow: a search/locate step happened before reading files.",
            evidence=evidence,
        )]

    return []


def context_hygiene_signal(session_summary: dict) -> list[RuntimeSignal]:
    compactions = int(session_summary.get("compactions", 0) or 0)
    if compactions <= 0:
        return []
    prompts = int(session_summary.get("prompts", 0) or 0)
    level = "high" if compactions >= 2 else "medium"
    return [RuntimeSignal(
        kind="context_growth", level=level,
        message="This session has accumulated substantial context and needed compaction.",
        what_happened=f"{compactions} compaction event(s) across {prompts} prompt(s) in this session.",
        why_it_matters="Frequent compaction usually means the session has grown well beyond "
                       "what a single task needs.",
        try_instead="Consider starting a fresh session for unrelated follow-up work.",
        evidence={"compactions": compactions, "prompts": prompts},
    )]


def agent_delegation_signal(events: list[RuntimeEvent], prompt_context: dict | None) -> list[RuntimeSignal]:
    ctx = prompt_context or {}
    if ctx.get("task_type") not in ("investigation", "debugging"):
        return []
    if any(e.event_type == RuntimeEventType.SUBAGENT_STOP for e in events):
        return []  # already delegated — nothing to suggest

    file_dirs = set()
    for e in _pre_tool_events(events):
        if e.tool_name in (READ_TOOLS | EDIT_TOOLS):
            path = e.metadata.get("file_path")
            if path:
                file_dirs.add(str(Path(path).parent))

    if len(file_dirs) >= 4:
        return [RuntimeSignal(
            kind="agent_delegation_opportunity", level="low",
            message="This investigation touched several independent areas of the codebase "
                    "in the main session.",
            what_happened=f"{len(file_dirs)} distinct directories were read/edited without "
                          f"delegating to a subagent.",
            why_it_matters="Independent, multi-area investigations can sometimes be delegated "
                           "to keep the main session focused.",
            try_instead="Possible delegation opportunity for similar multi-area investigations.",
            evidence={"distinct_areas": len(file_dirs)},
        )]
    return []


def claude_md_repetition_signal(prompt_event: RuntimeEvent, claude_mds: list) -> list[RuntimeSignal]:
    tokens = prompt_event.metadata.get("tokens") or []
    word_count = prompt_event.metadata.get("word_count", 0)
    if not claude_mds or not tokens or word_count < 6:
        return []

    prompt_tokens = set(tokens)
    for doc in claude_mds:
        preview = getattr(doc, "preview", "") or ""
        for line in preview.splitlines():
            line = line.strip("-*# \t")
            line_tokens = tokenize(line)
            if len(line_tokens) < 4:
                continue
            shared = prompt_tokens & line_tokens
            if len(shared) / len(line_tokens) >= 0.5 and len(shared) >= 3:
                return [RuntimeSignal(
                    kind="claude_md_repetition", level="low",
                    message="This looks like it may already be covered by an existing "
                            "CLAUDE.md instruction.",
                    what_happened=f"Prompt overlaps heavily with a line in {doc.path}.",
                    why_it_matters="Repeating an existing project rule in every prompt is "
                                   "extra typing that CLAUDE.md already covers.",
                    try_instead="Rely on the project instruction instead of restating it.",
                    evidence={"claude_md_path": doc.path, "matched_line": line[:120]},
                )]
    return []


def repeated_instructions_signal(
    prompt_events: list[RuntimeEvent], detected_skills: list | None = None,
    threshold: float = 0.35, min_occurrences: int = 3,
) -> list[RuntimeSignal]:
    """Cross-session repeated-workflow detection (spec section 10/11/33).

    Clusters UserPromptSubmit events by their stored token sets (never raw
    text) and, when a cluster repeats often enough, checks whether a real
    DETECTED Skill already covers it — producing the "existing Skill,
    performed manually" signal (section 11/33) instead of a generic
    "create a Skill" suggestion when one already exists.
    """
    candidates = [e for e in prompt_events if e.metadata.get("tokens")]
    if len(candidates) < min_occurrences:
        return []

    token_sets = [(set(e.metadata["tokens"]), e) for e in candidates]
    used = [False] * len(token_sets)
    clusters: list[list[RuntimeEvent]] = []

    for i in range(len(token_sets)):
        if used[i]:
            continue
        tokens_i, event_i = token_sets[i]
        cluster = [event_i]
        used[i] = True
        for j in range(i + 1, len(token_sets)):
            if used[j]:
                continue
            tokens_j, event_j = token_sets[j]
            if jaccard(tokens_i, tokens_j) >= threshold:
                cluster.append(event_j)
                used[j] = True
        if len(cluster) >= min_occurrences:
            clusters.append(cluster)

    signals: list[RuntimeSignal] = []
    for cluster in clusters:
        all_tokens: set = set()
        for e in cluster:
            all_tokens |= set(e.metadata["tokens"])

        matched_skill = None
        if detected_skills:
            for skill in detected_skills:
                skill_tokens = tokenize(f"{skill.name} {skill.description}")
                if not skill_tokens:
                    continue
                overlap = len(all_tokens & skill_tokens) / len(skill_tokens)
                if overlap >= 0.2:
                    matched_skill = skill
                    break

        if matched_skill:
            signals.append(RuntimeSignal(
                kind="skill_underused", level="medium",
                message=f"You have an existing Skill ('{matched_skill.name}') for this kind "
                        f"of work, but this workflow has been performed manually "
                        f"{len(cluster)} times.",
                what_happened=f"{len(cluster)} similar prompts detected across your history.",
                why_it_matters="A matching Skill already exists — repeating the workflow "
                               "manually forgoes its consistency.",
                try_instead=f"Use the '{matched_skill.name}' Skill instead of repeating the "
                            f"steps manually.",
                evidence={"occurrences": len(cluster), "skill": matched_skill.name},
            ))
        else:
            signals.append(RuntimeSignal(
                kind="repeated_workflow_no_skill", level="medium",
                message=f"A similar workflow has repeated {len(cluster)} times with no "
                        f"matching Skill detected.",
                what_happened=f"{len(cluster)} similar prompts detected across your history.",
                why_it_matters="A recurring multi-step workflow is a good candidate for a "
                               "reusable Skill.",
                try_instead="Consider creating a Skill for this workflow.",
                evidence={"occurrences": len(cluster)},
            ))

    return signals


def session_coherence(events: list[RuntimeEvent]) -> tuple[int, list[RuntimeSignal]]:
    """Context Health (spec Features 6/8): does NOT penalize for session length —
    only for actual task switches and compaction events. A long, single-focus
    session scores the same as a short one; a short session with two unrelated
    tasks scores worse than a long, coherent one.
    """
    prompt_events = [e for e in events if e.event_type == RuntimeEventType.USER_PROMPT_SUBMIT]

    task_switches = 0
    for prev, curr in zip(prompt_events, prompt_events[1:]):
        prev_tokens = set(prev.metadata.get("tokens", []))
        curr_tokens = set(curr.metadata.get("tokens", []))
        overlap = jaccard(prev_tokens, curr_tokens)
        same_type = prev.metadata.get("task_type") == curr.metadata.get("task_type")
        if overlap < _TASK_SWITCH_OVERLAP_THRESHOLD and not same_type:
            task_switches += 1

    compactions = sum(1 for e in events if e.event_type == RuntimeEventType.PRE_COMPACT)

    health = 100 - task_switches * _TASK_SWITCH_PENALTY - compactions * _COMPACTION_PENALTY
    health = max(0, min(100, health))

    signals: list[RuntimeSignal] = []
    if task_switches >= 2:
        signals.append(RuntimeSignal(
            kind="context_noisy", level="high" if task_switches >= 3 else "medium",
            message="Your current session contains multiple unrelated tasks.",
            what_happened=f"{task_switches} apparent task switch(es) detected in this session.",
            why_it_matters="Unrelated context accumulates and can dilute focus on the "
                           "current task.",
            try_instead="Consider starting a fresh session for the next unrelated task.",
            evidence={"task_switches": task_switches, "prompts": len(prompt_events)},
        ))
    elif len(prompt_events) >= 3:
        signals.append(RuntimeSignal(
            kind="context_coherent", level="low",
            message="Current task remains coherent with the session's history.",
            evidence={"prompts": len(prompt_events)},
        ))

    return health, signals


def verification_signal(events: list[RuntimeEvent]) -> list[RuntimeSignal]:
    """Spec Feature 9: never claims certainty either way — only reports
    whether verification *evidence* was observed in this session's events.
    """
    edit_indices = [
        i for i, e in enumerate(events)
        if e.event_type == RuntimeEventType.PRE_TOOL_USE and e.tool_name in EDIT_TOOLS
    ]
    if not edit_indices:
        return []

    last_edit = max(edit_indices)
    for e in events[last_edit + 1:]:
        if (e.event_type == RuntimeEventType.PRE_TOOL_USE and e.tool_name in EXEC_TOOLS
                and any(w in (e.metadata.get("command") or "").lower() for w in _TEST_COMMAND_WORDS)):
            return [RuntimeSignal(
                kind="verification_done", level="low",
                message="Test/verification activity observed after the change.",
                evidence={"command": e.metadata.get("command", "")},
            )]
        if e.event_type == RuntimeEventType.SUBAGENT_STOP:
            return [RuntimeSignal(
                kind="verification_done", level="low",
                message="A subagent ran after the change, which may include verification.",
            )]

    return [RuntimeSignal(
        kind="verification_missing", level="medium",
        message="Implementation changed but no verification activity was observed.",
        what_happened="A file edit occurred with no test/verification command "
                      "afterward in this session.",
        why_it_matters="Unverified changes carry more risk of being wrong or incomplete "
                       "— though verification may simply have happened outside what "
                       "this app can observe.",
        try_instead="Review the diff and run the affected tests.",
        evidence={"edits_after_which_no_verification_seen": len(edit_indices)},
    )]


def analyze_session(
    events: list[RuntimeEvent], session_summary: dict, *,
    latest_prompt_context: dict | None = None, claude_mds: list | None = None,
) -> list[RuntimeSignal]:
    """All per-session signals (excludes the cross-session repeated-instructions
    signal, which the caller computes once across recent history, not per session).
    """
    signals: list[RuntimeSignal] = []
    signals.extend(search_first_signal(events, latest_prompt_context))
    signals.extend(context_hygiene_signal(session_summary))
    signals.extend(agent_delegation_signal(events, latest_prompt_context))
    signals.extend(verification_signal(events))

    _health, coherence_signals = session_coherence(events)
    signals.extend(coherence_signals)

    if claude_mds:
        prompt_events = [e for e in events if e.event_type == RuntimeEventType.USER_PROMPT_SUBMIT]
        if prompt_events:
            signals.extend(claude_md_repetition_signal(prompt_events[-1], claude_mds))

    return signals
