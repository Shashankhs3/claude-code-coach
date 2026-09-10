"""Deterministic templates the rewriter assembles from — no AI API involved.

Every template only ever contains neutral wording; specifics (files, error
descriptions, constraints) are spliced in from `prompt_extractor.PromptExtraction`
when present. Nothing here invents a technical fact.
"""

from __future__ import annotations

# The exact canonical rewrite for a fully vague, no-information prompt
# (spec's own "Fix my project." -> ... example).
VAGUE_GOAL_REWRITE = (
    "Investigate the issue in the project and identify the root cause before "
    "making changes.\n\n"
    "Limit changes to what is necessary for the identified issue.\n\n"
    "Run the relevant tests after implementing the fix and summarize the root "
    "cause, files changed, and test results."
)

NO_REWRITE_CLEAR = "Clear task. No major rewrite recommended."

NO_REWRITE_INFORMATIONAL = (
    "This is an information request — coding-task criteria (scope, "
    "constraints, verification) don't apply here. No rewrite needed."
)

OVERLY_PRESCRIPTIVE_NOTE = (
    "This prompt is very detailed and prescriptive. That's not wrong, but "
    "consider whether Claude needs every step spelled out, or could use its "
    "own judgment for some of it."
)
