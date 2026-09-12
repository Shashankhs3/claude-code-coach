"""Level 5 (CLAUDE.md) and Level 6 (Skills)."""

from __future__ import annotations

from ..models import Level, Lesson, QuizOption, QuizQuestion, TryIt
from .sources import CLAUDE_CODE_MEMORY, CLAUDE_CODE_SKILLS, coach

LEVEL_5 = Level(
    id="5",
    title="CLAUDE.md",
    lessons=(
        Lesson(
            id="5.1",
            title="What CLAUDE.md is",
            objective="Explain CLAUDE.md's role as persistent, always-loaded project instructions.",
            what=(
                "CLAUDE.md is a persistent instruction file Claude reads at the start of "
                "every conversation in the project."
            ),
            why="It gives Claude project knowledge it can't reliably infer from code alone.",
            example=(
                "Stable project conventions, commands Claude can't guess, architecture "
                "constraints, testing rules, and recurring project-specific knowledge."
            ),
            takeaway="CLAUDE.md is for what applies to every session, stated once.",
            sources=(CLAUDE_CODE_MEMORY,),
        ),
        Lesson(
            id="5.2",
            title="What does NOT belong in CLAUDE.md",
            objective="Recognize when CLAUDE.md has grown past what it should hold.",
            what="Don't turn CLAUDE.md into the entire project manual.",
            why=(
                "Documented guidance is direct here: if a bloated CLAUDE.md is too long, "
                "Claude ignores half of it because important rules get lost in the noise."
            ),
            better_approach=(
                "A community pattern is keeping always-loaded instructions lean and putting "
                "detailed documentation elsewhere for conditional retrieval — for example, "
                "as a Skill loaded only when relevant."
            ),
            quiz=(
                QuizQuestion(
                    prompt="For each line in CLAUDE.md, what question does documented "
                    "guidance suggest asking?",
                    options=(
                        QuizOption('"Would removing this cause Claude to make a mistake?"',
                                   correct=True),
                        QuizOption('"Is this at least 3 sentences long?"'),
                        QuizOption('"Did I write this today?"'),
                    ),
                    explanation=(
                        "If removing a line wouldn't cause a mistake, it's a candidate to cut."
                    ),
                ),
            ),
            takeaway="Keep CLAUDE.md lean; move conditional or detailed material elsewhere.",
            sources=(CLAUDE_CODE_MEMORY,),
        ),
        Lesson(
            id="5.3",
            title="CLAUDE.md lab",
            objective="Pick the better of several example CLAUDE.md excerpts and say why.",
            what="Which of these four CLAUDE.md excerpts is the best fit?",
            quiz=(
                QuizQuestion(
                    prompt="Pick the better CLAUDE.md excerpt.",
                    options=(
                        QuizOption(
                            "A 40-page file describing every function in the codebase "
                            "file-by-file (too large)"
                        ),
                        QuizOption('"Write good code and be careful." (too vague)'),
                        QuizOption(
                            '"Use ES modules, not CommonJS. Run the single affected test '
                            'file, not the whole suite, after a change." (concrete, '
                            "concise)", correct=True,
                        ),
                        QuizOption(
                            "The same two testing instructions repeated in five different "
                            "sections (too repetitive)"
                        ),
                    ),
                    explanation=(
                        "Concrete, non-obvious rules Claude can't infer from the code — "
                        "stated once — are what belongs here."
                    ),
                ),
            ),
            takeaway="Good CLAUDE.md content is concrete, non-obvious, and stated once.",
            sources=(CLAUDE_CODE_MEMORY,),
        ),
    ),
)

LEVEL_6 = Level(
    id="6",
    title="Skills",
    lessons=(
        Lesson(
            id="6.1",
            title="What a Skill is",
            objective="Contrast a one-off prompt with a packaged, reusable workflow.",
            what="A reusable workflow or expertise package for a recurring kind of task.",
            why="It's performed consistently instead of re-explained from scratch each time.",
            example="Prompt = this task. Skill = this repeatable workflow.",
            takeaway="A Skill packages a workflow you'd otherwise re-explain every time.",
            sources=(CLAUDE_CODE_SKILLS,),
        ),
        Lesson(
            id="6.2",
            title="When NOT to create a Skill",
            objective="Recognize one-off work that doesn't justify a Skill.",
            what="A one-time task, a temporary experiment, or a unique investigation.",
            why="A Skill is only worth the overhead if the workflow will actually repeat.",
            quiz=(
                QuizQuestion(
                    prompt="You need to investigate one unusual, unlikely-to-recur bug. "
                    "Should you build a Skill for it first?",
                    options=(
                        QuizOption("No — it's a one-time investigation", correct=True),
                        QuizOption("Yes — always build a Skill before any investigation"),
                    ),
                    explanation="A Skill is for repeatable workflows, not one-off work.",
                ),
            ),
            takeaway="Not every task deserves a Skill — only the ones that will repeat.",
            sources=(CLAUDE_CODE_SKILLS,),
        ),
        Lesson(
            id="6.3",
            title="Skill candidate detector",
            objective="Read DETECTED / POSSIBLE / INFERRED / UNKNOWN correctly.",
            what=(
                "The Coach classifies every claim about your environment with one of four "
                "labels: DETECTED (an actual file found on disk right now), POSSIBLE (a "
                "match between your prompt and a detected resource), INFERRED (the Coach's "
                "own historical-pattern heuristic, no resource confirmed), or UNKNOWN "
                "(discovery couldn't complete)."
            ),
            why=(
                "Never treat an INFERRED skill candidate as one that already exists — it's "
                "a pattern-based suggestion, not a scan result."
            ),
            try_it=TryIt(
                instructions="Open Skills to see real candidates classified this way.",
                related_page="Skills",
            ),
            takeaway="INFERRED means \"the Coach suspects this,\" not \"this exists.\"",
            sources=(coach("The DETECTED/POSSIBLE/INFERRED/UNKNOWN model is the Coach's own "
                            "provenance system, not an Anthropic concept."),),
        ),
        Lesson(
            id="6.4",
            title="Skill design lab",
            objective="Turn a repeated workflow into an actual Skill using the Skill Creator.",
            what="Pick a workflow you repeat often and convert it into a Skill.",
            try_it=TryIt(
                instructions="Use the Skill Creator to draft a Skill from a real repeated "
                "workflow of yours.",
                related_page="Skill Creator",
                action_label="Open Skill Creator",
            ),
            takeaway="The best way to learn Skills is building one from something you actually repeat.",
            sources=(CLAUDE_CODE_SKILLS,),
        ),
    ),
)
