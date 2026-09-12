"""Level 17 (Real Scenario Lab), Level 18 (Interactive Prompt Lab), and
Level 19 (Capability Decision Tree)."""

from __future__ import annotations

from ..models import Level, Lesson, QuizOption, QuizQuestion, TryIt
from .sources import coach

_SCENARIO_TAKEAWAY = "Real decisions, not memorized rules, are what this course is teaching."


def _scenario(id_: str, title: str, situation: str, options: tuple[QuizOption, ...],
              explanation: str) -> Lesson:
    return Lesson(
        id=id_,
        title=title,
        objective=f"Choose the right approach for: {title.lower()}.",
        what=situation,
        quiz=(QuizQuestion(prompt="Best approach?", options=options, explanation=explanation),),
        takeaway=_SCENARIO_TAKEAWAY,
        sources=(coach("Scenario lab — illustrative, not a real logged session."),),
    )


LEVEL_17 = Level(
    id="17",
    title="Real Scenario Lab",
    lessons=(
        _scenario(
            "17.1", "Scenario 1 — one-line UI bug",
            "Fix a one-line UI bug: a button has the wrong label.",
            (QuizOption("Prompt", correct=True), QuizOption("Agent"), QuizOption("Skill")),
            "Small, scoped, one-off — a direct prompt is enough.",
        ),
        _scenario(
            "17.2", "Scenario 2 — unknown subsystem",
            "Investigate a large, unfamiliar subsystem you've never touched before.",
            (QuizOption("Agent / targeted exploration", correct=True),
             QuizOption("One giant prompt"), QuizOption("CLAUDE.md")),
            "Broad, independent investigation is exactly what delegation or targeted "
            "exploration is for.",
        ),
        _scenario(
            "17.3", "Scenario 3 — repeated deployment",
            "Run the same deployment workflow you've now repeated 20 times.",
            (QuizOption("Skill", correct=True), QuizOption("Prompt every time"),
             QuizOption("Agent")),
            "A workflow you keep repeating is precisely what a Skill packages.",
        ),
        _scenario(
            "17.4", "Scenario 4 — stable architecture rule",
            "Your project has a stable architecture rule that should always apply.",
            (QuizOption("CLAUDE.md", correct=True), QuizOption("A one-time prompt"),
             QuizOption("MCP")),
            "A rule that should always apply belongs in the always-loaded CLAUDE.md.",
        ),
        _scenario(
            "17.5", "Scenario 5 — external system capability",
            "You need Claude to query a live external system it can't otherwise reach.",
            (QuizOption("MCP", correct=True), QuizOption("CLAUDE.md"), QuizOption("A hook")),
            "External capability access is MCP's job.",
        ),
        _scenario(
            "17.6", "Scenario 6 — three unrelated tasks",
            "Your session now contains three unrelated tasks tangled together.",
            (QuizOption("Fresh session / clear", correct=True),
             QuizOption("Keep going in the same session"), QuizOption("Compact")),
            "Unrelated tasks tangled together is the case for starting fresh, not compacting.",
        ),
        _scenario(
            "17.7", "Scenario 7 — long but coherent task",
            "Your task is long but still one coherent thing, and context is getting noisy.",
            (QuizOption("Compact", correct=True), QuizOption("Fresh session"),
             QuizOption("Add everything to CLAUDE.md")),
            "Coherent history worth keeping, just noisy — that's what compaction is for.",
        ),
    ),
)

LEVEL_18 = Level(
    id="18",
    title="Interactive Prompt Lab",
    lessons=(
        Lesson(
            id="18.1",
            title="Diagnose a real prompt",
            objective="Read a full diagnostic on a real prompt: ambiguity, scope, and risk.",
            what=(
                "Enter a real prompt below. The Coach detects ambiguity, scope, unnecessary "
                "detail, missing completion criteria, a broad-vs-narrow mismatch, and "
                "possible Skill, Agent, or CLAUDE.md opportunities — then shows your "
                "approach, why, and a better approach."
            ),
            why="This is the same deterministic analyzer from Lesson 1.3, now read for the "
                "full picture rather than just a rewrite.",
            try_it=TryIt(
                instructions="Type a prompt above to see its full diagnostic breakdown.",
                related_page="Prompt Inspector",
                action_label="Open the full Prompt Inspector",
            ),
            takeaway="A real diagnostic on your own prompt teaches more than another example.",
            sources=(coach("Reuses the Coach's deterministic analyzer."),),
            interactive="prompt_lab",
        ),
    ),
)

LEVEL_19 = Level(
    id="19",
    title="Capability Decision Tree",
    lessons=(
        Lesson(
            id="19.1",
            title="Capability decision wizard",
            objective="Walk a real task through the full capability decision tree — one-off, "
                       "repeatable, independent, stable, external, or noisy-context.",
            what=(
                "Answer a few questions about what you're trying to do, and see which "
                "mechanism the tree points to — Prompt, Skill, Agent, CLAUDE.md, MCP, "
                "Compact, or Fresh session."
            ),
            why="The wizard isn't mechanically absolute — if your own judgment disagrees "
                "with its suggestion, that's fine; the point is understanding the reasoning, "
                "not obeying the tree.",
            takeaway="The tree is a starting heuristic, not a verdict you're bound to follow.",
            sources=(coach("Decision wizard — a Coach heuristic, override it when your own "
                            "judgment says otherwise."),),
            interactive="decision_wizard",
        ),
    ),
)
