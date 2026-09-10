"""Single-prompt opportunity signals.

These are per-prompt, conservative signals only. Section 10/11 of the spec
is clear that a *confirmed* Skill/Agent/CLAUDE.md candidate requires
repeated evidence across history — that aggregation lives in
``analytics.patterns``. This module only flags what a single prompt, in
isolation, suggests — always phrased as a possibility, never a mandate.
"""

from __future__ import annotations

from . import lexicon as lex
from .models import Opportunity
from .task_classifier import TaskClassification, TaskType


def detect(prompt: str, low: str, classification: TaskClassification) -> list[Opportunity]:
    opportunities: list[Opportunity] = []

    # ---- Repeatable-workflow / Skill signal (single occurrence) -----------
    workflow_markers = len(lex.REPETITIVE_TRIGGER.findall(low))
    checklist_markers = len(lex.CHECKLIST_STEP_WORDS.findall(low))
    if workflow_markers >= 1 and checklist_markers >= 2:
        opportunities.append(
            Opportunity(
                kind="skill",
                message="This looks like a repeatable, multi-step workflow.",
                confidence="medium" if workflow_markers >= 1 and checklist_markers >= 3 else "low",
                reason="Repetition language plus a consistent multi-step checklist.",
            )
        )

    # ---- Independent-investigation / Agent signal --------------------------
    investigation_verb_hits = len(lex.INDEPENDENT_INVESTIGATION_VERBS.findall(low))
    word_count = len(prompt.split())
    if investigation_verb_hits >= 2 and word_count >= 20:
        confidence = "high" if investigation_verb_hits >= 3 and word_count >= 35 else "medium"
        opportunities.append(
            Opportunity(
                kind="agent",
                message="This looks like a substantial, independent investigation.",
                confidence=confidence,
                reason="Multiple analysis verbs (investigate/trace/compare/...) across a "
                "long, multi-part request.",
            )
        )

    # ---- Persistent project rule / CLAUDE.md signal ------------------------
    if lex.PERSISTENT_RULE_TRIGGER.search(low) and lex.PERSISTENT_RULE_DOMAIN.search(low):
        opportunities.append(
            Opportunity(
                kind="claude_md",
                message="This reads like a persistent project rule rather than a one-off task.",
                confidence="medium",
                reason="'always/never/must' language tied to a durable project concern "
                "(tests, migrations, security, conventions).",
            )
        )

    # ---- Context noise signal -----------------------------------------------
    if lex.CONTEXT_HEAVY_WORDS.search(low):
        opportunities.append(
            Opportunity(
                kind="context",
                message="This prompt references a lot of prior discussion — the "
                "surrounding session context may be larger than this task needs.",
                confidence="medium",
                reason="Explicit reference to prior/whole conversation history.",
            )
        )

    # ---- Search-first signal -------------------------------------------------
    has_search = bool(lex.SEARCH_VERBS.search(low))
    has_broad_read = bool(lex.BROAD_READ.search(low))
    if has_broad_read and not has_search and classification.primary in (
        TaskType.DEBUGGING,
        TaskType.INVESTIGATION,
        TaskType.IMPLEMENTATION,
        TaskType.REFACTORING,
        TaskType.MIXED,
    ):
        opportunities.append(
            Opportunity(
                kind="search_first",
                message="Consider searching/tracing to a likely location before reading "
                "broadly — it keeps context smaller.",
                confidence="medium",
                reason="Broad-read language ('entire repository', 'every file') without "
                "a search/locate step.",
            )
        )

    return opportunities
