"""Deterministic, local-only prompt suggestion engine (spec Feature 1).

No external AI API. A suggestion is assembled from the prompt's own
extracted facts (see prompt_extractor.py) plus neutral template language for
whatever is missing — never invented specifics. See prompt_templates.py for
the fixed strings this pulls from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from . import prompt_templates as tpl
from .models import AnalysisResult
from .prompt_analyzer import analyze_prompt
from .prompt_extractor import PromptExtraction, extract

_PRESCRIPTIVE_STEPS = re.compile(
    r"\b(step\s*\d|^\s*\d+[.)]\s|first,.*then,.*then)\b", re.I | re.M
)


class PromptCategory(str, Enum):
    GOOD = "good"
    UNDERSPECIFIED = "underspecified"
    OVERLY_PRESCRIPTIVE = "overly_prescriptive"
    BROAD_JUSTIFIED = "broad_justified"
    BROAD_INEFFICIENT = "broad_inefficient"
    INFORMATIONAL = "informational"
    EMPTY = "empty"


_TASK_VERB = {
    "debugging": "Investigate and fix the issue",
    "investigation": "Investigate the issue",
    "implementation": "Implement the requested change",
    "refactoring": "Refactor the relevant code",
    "review": "Review the relevant code",
    "security_review": "Review the relevant code for security issues",
    "research": "Research the question",
    "repetitive_workflow": "Carry out the workflow",
}


@dataclass
class PromptSuggestion:
    category: PromptCategory
    message: str
    suggested_text: str | None = None
    extraction: PromptExtraction = field(default_factory=PromptExtraction)


def _compose_rewrite(prompt: str, analysis: AnalysisResult, extraction: PromptExtraction) -> str:
    lines: list[str] = []

    if extraction.error_descriptions:
        err = extraction.error_descriptions[0].rstrip(".").strip()
        goal = f"Investigate why {err[0].lower() + err[1:] if err[:1].isupper() else err}"
    else:
        goal = _TASK_VERB.get(analysis.task_type, "Address the issue")

    focus = extraction.files or extraction.domain_areas[:3]
    if focus:
        goal += f", focusing on {', '.join(focus)}"
    lines.append(goal.strip().rstrip(".") + ".")

    for c in extraction.constraints:
        text = c.rstrip(".").strip()
        if text:
            lines.append((text[0].upper() + text[1:]).rstrip(".") + ".")

    if not extraction.constraints and analysis.task_type in ("implementation", "refactoring"):
        lines.append("Keep the change minimal and consistent with existing conventions.")

    if analysis.task_type in ("debugging", "implementation", "refactoring"):
        lines.append("Implement the minimal necessary fix and run the relevant tests.")
    else:
        lines.append("Investigate thoroughly and report findings before making any changes.")

    done_bits = []
    if extraction.error_descriptions:
        done_bits.append("the issue is resolved")
    done_bits.append("relevant tests pass")
    if analysis.dimension_status("output") != "clear":
        done_bits.append("the root cause and changed files are summarized")
    lines.append("Done when " + ", ".join(done_bits) + ".")

    return "\n\n".join(lines)


def suggest_prompt(prompt: str, analysis: AnalysisResult | None = None) -> PromptSuggestion:
    if not prompt.strip():
        return PromptSuggestion(PromptCategory.EMPTY, "Nothing to suggest for an empty prompt.")

    analysis = analysis or analyze_prompt(prompt)
    extraction = extract(prompt)

    if analysis.task_type in ("information", "explanation"):
        return PromptSuggestion(
            PromptCategory.INFORMATIONAL, tpl.NO_REWRITE_INFORMATIONAL, None, extraction,
        )

    if analysis.vague_goal:
        return PromptSuggestion(
            PromptCategory.UNDERSPECIFIED,
            "Prompt is significantly underspecified — goal, scope, and verification "
            "are all unclear.",
            tpl.VAGUE_GOAL_REWRITE,
            extraction,
        )

    word_count = len(prompt.split())
    if (word_count > 60 and len(extraction.constraints) >= 3
            and _PRESCRIPTIVE_STEPS.search(prompt)):
        return PromptSuggestion(
            PromptCategory.OVERLY_PRESCRIPTIVE, tpl.OVERLY_PRESCRIPTIVE_NOTE, None, extraction,
        )

    justified_broad = (
        analysis.breadth_level >= 1
        or analysis.task_type in ("review", "security_review", "research", "repetitive_workflow")
    )

    if analysis.rating in ("GOOD", "EXCELLENT"):
        if justified_broad and analysis.breadth_level >= 1:
            return PromptSuggestion(
                PromptCategory.BROAD_JUSTIFIED,
                "This looks intentionally broad for this kind of task — that's fine.",
                None, extraction,
            )
        if (analysis.rating == "GOOD" and analysis.dimension_status("done") == "missing"
                and analysis.task_type in ("implementation", "refactoring", "debugging")):
            return PromptSuggestion(
                PromptCategory.GOOD,
                "Clear task. Consider adding a brief 'Done when...' condition so "
                "there's an explicit way to confirm it's finished.",
                None, extraction,
            )
        return PromptSuggestion(PromptCategory.GOOD, tpl.NO_REWRITE_CLEAR, None, extraction)

    if justified_broad and not extraction.constraints:
        return PromptSuggestion(
            PromptCategory.BROAD_JUSTIFIED,
            "Broad scope looks appropriate for this kind of task, though adding an "
            "output format would help keep the response focused.",
            None, extraction,
        )

    if analysis.breadth_level >= 2 and not justified_broad:
        return PromptSuggestion(
            PromptCategory.BROAD_INEFFICIENT,
            "This task looks narrower than the requested scope suggests — reading "
            "broadly here may pull in unnecessary context.",
            _compose_rewrite(prompt, analysis, extraction),
            extraction,
        )

    return PromptSuggestion(
        PromptCategory.UNDERSPECIFIED,
        "Some useful information is present, but the task, scope, or verification "
        "could be sharper.",
        _compose_rewrite(prompt, analysis, extraction),
        extraction,
    )
