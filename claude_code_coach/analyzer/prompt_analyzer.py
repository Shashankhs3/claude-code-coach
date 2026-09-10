"""The main prompt analyzer: dimension evaluation, scoring, and coaching text.

Core principle (spec section 3): evaluate on evidence, not keyword presence.
Missing information is not automatically bad — it depends on task type
(spec section 5) and on whether the dimension is even applicable.
"""

from __future__ import annotations

import re

from . import lexicon as lex
from . import opportunities as opp
from .models import AnalysisResult, DimensionResult
from .scoring import score_prompt
from .task_classifier import TaskClassification, TaskType, classify


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _is_vague_goal(prompt: str) -> bool:
    return any(p.match(prompt) for p in lex.VAGUE_GOAL_PATTERNS)


def _analyze_goal(
    prompt: str, low: str, cls: TaskClassification, vague: bool
) -> DimensionResult:
    if vague:
        return DimensionResult("missing", "The requested outcome or problem is not identified.")

    if cls.informational:
        return DimensionResult("clear", "Clear information/explanation request.")

    concrete_noun = bool(lex.CONCRETE_DOMAIN_NOUN.search(low))
    concrete_path = bool(lex.PATH_PATTERN.search(low)) or bool(re.search(r"`[^`]+`", low))
    why_problem = bool(re.search(r"\bwhy\b.*\b(return|fail|break|crash|error|timeout)\b", low))
    long_with_outcome = len(prompt.split()) >= 8 and bool(
        lex.CONCRETE_OUTCOME_VERB.search(low)
    )

    if concrete_noun or concrete_path or why_problem:
        return DimensionResult("clear", "A concrete target, file, or problem is named.")
    if long_with_outcome:
        return DimensionResult("partial", "An outcome is implied but not sharply scoped.")

    if cls.primary == TaskType.MIXED and not cls.signals.get("action"):
        return DimensionResult("missing", "No clear task or information goal detected.")

    return DimensionResult(
        "missing", "An action is requested, but the specific problem or outcome is unclear."
    )


def _analyze_scope(prompt: str, low: str, cls: TaskClassification) -> DimensionResult:
    has_path = bool(lex.PATH_PATTERN.search(prompt))
    has_scope_language = bool(lex.SCOPE_LANGUAGE.search(low))

    if has_path or has_scope_language:
        return DimensionResult("clear", "Scope is bounded to specific files/areas.")

    if cls.informational:
        # A targeted question ("what handles login?") doesn't need an
        # explicit scope statement to be a good prompt.
        return DimensionResult("na")

    # A recurring workflow's "scope" is the trigger it applies to (every PR,
    # every new endpoint), not a file path.
    if cls.primary == TaskType.REPETITIVE_WORKFLOW and lex.REPETITIVE_TRIGGER.search(low):
        return DimensionResult("clear", "The workflow's trigger/scope is defined.")

    # Naming several concrete subsystems (without a file path) is more
    # bounded than an unscoped prompt, even if it isn't a precise path.
    domain_hits = len(set(lex.CONCRETE_DOMAIN_NOUN.findall(low)))
    if domain_hits >= 2:
        return DimensionResult(
            "partial", "Specific components are named, though not exact files/directories."
        )

    return DimensionResult("missing", "No specific files/directories/areas are named.")


def _analyze_investigation(prompt: str, low: str, cls: TaskClassification) -> DimensionResult:
    has_search = bool(lex.SEARCH_VERBS.search(low))
    has_broad_read = bool(lex.BROAD_READ.search(low))

    if cls.primary in (TaskType.INFORMATION, TaskType.EXPLANATION):
        return DimensionResult("na")

    if has_search:
        return DimensionResult("clear", "A search/locate/trace strategy is specified.")
    if has_broad_read:
        return DimensionResult(
            "missing", "Asks for broad reading; search/narrow first where possible."
        )
    return DimensionResult("na")


def _analyze_constraints(prompt: str, low: str, cls: TaskClassification) -> DimensionResult:
    if cls.informational or cls.primary == TaskType.RESEARCH:
        return DimensionResult("na")

    if lex.CONSTRAINT_WORDS.search(low):
        return DimensionResult("clear", "Useful constraints are specified.")

    return DimensionResult(
        "missing", "No constraints given (e.g. what not to change, conventions to keep)."
    )


def _analyze_done(prompt: str, low: str, cls: TaskClassification) -> DimensionResult:
    if cls.informational:
        return DimensionResult("na")

    if lex.DONE_WORDS.search(low):
        return DimensionResult("clear", "A definition of done / verification step is given.")

    if cls.primary in (TaskType.IMPLEMENTATION, TaskType.REFACTORING, TaskType.DEBUGGING,
                       TaskType.INVESTIGATION, TaskType.SECURITY_REVIEW,
                       TaskType.REPETITIVE_WORKFLOW):
        return DimensionResult("missing", "No 'done when...'/verification criteria given.")

    return DimensionResult("na")


def _analyze_output(prompt: str, low: str, cls: TaskClassification) -> DimensionResult:
    if lex.OUTPUT_WORDS.search(low):
        return DimensionResult("clear", "Output format/scope is reasonably controlled.")

    if cls.informational:
        # Missing output formatting is a nice-to-have for a simple
        # information/explanation request, not a real quality problem —
        # don't let it drag the score down (spec section 27).
        return DimensionResult(
            "partial", "Consider specifying the format/level of detail you want back."
        )

    if cls.primary in (TaskType.REVIEW, TaskType.SECURITY_REVIEW,
                       TaskType.REPETITIVE_WORKFLOW, TaskType.RESEARCH):
        return DimensionResult(
            "missing", "Consider specifying the format/level of detail you want back."
        )

    return DimensionResult("na")


def _breadth_level(prompt: str, low: str) -> int:
    breadth = 0
    if lex.BREADTH_WORDS.search(low):
        breadth += 1
    if lex.UNBOUNDED_WORDS.search(low):
        breadth += 1
    if len(prompt.split()) > 80:
        breadth += 1
    return breadth


def analyze_prompt(prompt: str) -> AnalysisResult:
    p = prompt.strip()

    if not p:
        return AnalysisResult(
            prompt=prompt,
            task_type=TaskType.MIXED.value,
            dimensions={},
            score=0,
            rating="POOR",
            warnings=["Prompt is empty."],
        )

    low = p.lower()
    cls = classify(p)

    vague_goal = _is_vague_goal(p)
    overly_broad_fix = bool(lex.BROAD_FIX_EVERYTHING.search(low))
    breadth_level = _breadth_level(p, low)

    dims = {
        "goal": _analyze_goal(p, low, cls, vague_goal),
        "scope": _analyze_scope(p, low, cls),
        "investigation": _analyze_investigation(p, low, cls),
        "constraints": _analyze_constraints(p, low, cls),
        "done": _analyze_done(p, low, cls),
        "output": _analyze_output(p, low, cls),
    }

    # A small, concretely-scoped fix (e.g. "fix the typo in `x.py`") doesn't
    # need a formal constraints/done statement to be a good prompt — the
    # blast radius is self-evidently tiny. This must not depend on total
    # prompt length, since unrelated preceding context (spec section 15)
    # can make an otherwise-tiny instruction look long.
    trivial_task = (
        dims["scope"].status == "clear"
        and bool(lex.TRIVIAL_ACTION.search(low))
        and cls.primary in (TaskType.IMPLEMENTATION, TaskType.REFACTORING, TaskType.DEBUGGING)
        and not vague_goal
    )
    if trivial_task:
        for key in ("constraints", "done"):
            if dims[key].status == "missing":
                dims[key] = DimensionResult("na")

    # A recurring workflow's own checklist (check/verify/confirm/validate
    # steps) functions as an implicit acceptance criteria and output
    # format, even without a literal "done when..." / "return a table..."
    # phrase.
    if cls.primary == TaskType.REPETITIVE_WORKFLOW:
        checklist_count = len(lex.CHECKLIST_STEP_WORDS.findall(low))
        if checklist_count >= 3:
            for key in ("done", "output"):
                if dims[key].status == "missing":
                    dims[key] = DimensionResult(
                        "partial", dims[key].detail or "Implied by the checklist steps."
                    )

    overly_broad_read = dims["investigation"].status == "missing" and bool(
        lex.BROAD_READ.search(low)
    )

    low_effort = vague_goal or overly_broad_fix or (
        breadth_level >= 2 and dims["goal"].status == "missing"
    )

    score, rating = score_prompt(
        cls.primary,
        dims,
        breadth_level=breadth_level,
        overly_broad_read=overly_broad_read,
        low_effort=low_effort,
    )

    good: list[str] = []
    warnings: list[str] = []

    for dim in dims.values():
        if not dim.applicable:
            continue
        if dim.status == "clear":
            good.append(dim.detail)
        elif dim.status in ("missing", "partial") and dim.detail:
            warnings.append(dim.detail)

    if breadth_level >= 2:
        warnings.append("Task is unusually broad; narrow the scope to reduce unnecessary context.")

    if low_effort:
        # Keep the coaching short and to the point for very low-effort prompts.
        warnings = _dedupe(warnings)
        good = []
        opportunities_list = [
            opp.Opportunity(
                kind="search_first",
                message="State what is broken or what outcome you want.",
                confidence="high",
            ),
            opp.Opportunity(
                kind="search_first",
                message="Specify relevant files/directories or the area to investigate.",
                confidence="high",
            ),
            opp.Opportunity(
                kind="search_first",
                message="Add a clear 'Done when...' condition.",
                confidence="high",
            ),
        ]
    else:
        opportunities_list = opp.detect(p, low, cls)

    context_note = ""
    if any(o.kind == "context" for o in opportunities_list):
        context_note = "noisy"

    result = AnalysisResult(
        prompt=prompt,
        task_type=cls.primary.value,
        dimensions=dims,
        score=score,
        rating=rating,
        good=_dedupe(good),
        warnings=_dedupe(warnings),
        opportunities=opportunities_list,
        breadth_level=breadth_level,
        vague_goal=low_effort,
        context_note=context_note,
    )
    return result
