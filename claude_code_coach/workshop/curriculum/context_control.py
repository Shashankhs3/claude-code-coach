"""Level 2 (Search First / Context Control), Level 3 (Sessions), and
Level 4 (Compaction)."""

from __future__ import annotations

from ..models import Level, Lesson, QuizOption, QuizQuestion, TryIt
from .sources import (
    ANTHROPIC_CONTEXT_ENGINEERING,
    CLAUDE_CODE_BEST_PRACTICES,
    COMMUNITY_SESSION_HYGIENE,
    coach,
)

LEVEL_2 = Level(
    id="2",
    title="Search First / Context Control",
    lessons=(
        Lesson(
            id="2.1",
            title="Search → narrow → read → modify",
            objective="Explain why locating code before reading it keeps a narrow task efficient.",
            what=(
                "For a narrow task, search or locate the relevant code first, then read only "
                "what's relevant, then modify — rather than reading broadly hoping to find it."
            ),
            why="This keeps the context window focused on what the task actually needs.",
            example=(
                "Task: fix a timeout in the login flow.\n\nPoor: “Read the repository.”"
                "\n\nBetter: “Find authentication timeout handling, then inspect only the "
                "relevant implementation and tests.”"
            ),
            better_approach=(
                "The exception: repository-wide understanding is correct when the task "
                "itself is repository-wide — onboarding, architecture review, or a migration "
                "genuinely need broad reading. Search-first is a pattern for narrow tasks, "
                "not a rule against ever reading broadly."
            ),
            quiz=(
                QuizQuestion(
                    prompt="You're investigating architecture before a major migration. "
                    "Should Claude read broadly?",
                    options=(
                        QuizOption("No — broad reading is never justified"),
                        QuizOption(
                            "Yes — the task itself is repository-wide, so broad context is "
                            "appropriate", correct=True,
                        ),
                        QuizOption("Only if the repository has fewer than 10 files"),
                    ),
                    explanation=(
                        "Context efficiency means the right amount of context for the job — "
                        "not the smallest possible context in every case."
                    ),
                ),
            ),
            takeaway="Search-first suits narrow tasks; broad tasks can justify broad reading.",
            sources=(CLAUDE_CODE_BEST_PRACTICES,),
        ),
        Lesson(
            id="2.2",
            title="Don't read everything by default",
            objective="Practice sorting files into relevant vs unrelated for a given task.",
            what=(
                "Below is a simulated file list for a task. Mark each file relevant or "
                "unrelated, then see how that choice affects a simple context meter."
            ),
            why=(
                "Deciding what's actually relevant is a skill in itself — reading "
                "everything \"just in case\" is its own kind of unnecessary context."
            ),
            takeaway="Relevance is a judgment call worth making deliberately, not a default.",
            sources=(coach("Simulated exercise — the file list is illustrative, not scanned "
                            "from a real repository."),),
            interactive="context_meter",
        ),
        Lesson(
            id="2.3",
            title="Tool output is context too",
            objective="Recognize that command output consumes context exactly like file content.",
            what=(
                "Command output becomes context the same way file contents do — a giant log "
                "dump is just as much context weight as reading an entire unrelated file."
            ),
            why="Excessive command output can crowd out what's actually relevant to the task.",
            bad_approach='"cat giant-log.txt" and scroll through all of it.',
            better_approach=(
                "Search for the relevant error first, then inspect the surrounding lines — "
                "targeted inspection instead of dumping everything."
            ),
            takeaway="Ask for targeted output, not a full dump you'll filter yourself.",
            sources=(ANTHROPIC_CONTEXT_ENGINEERING,),
        ),
    ),
)

LEVEL_3 = Level(
    id="3",
    title="Sessions",
    lessons=(
        Lesson(
            id="3.1",
            title="One task or many?",
            objective="Decide whether new work belongs in the current session or a fresh one.",
            what=(
                "A coherent task worth continuing stays in the same session. A genuinely "
                "different task is worth considering for a fresh session instead."
            ),
            why="Unrelated work accumulating in one session can pollute its context.",
            better_approach=(
                "Community guidance commonly recommends clearing between unrelated tasks. "
                "This is a widely shared habit, not a hard Anthropic requirement — but "
                "Anthropic's own guidance does warn that a session mixing unrelated work "
                "ends up with context full of irrelevant information."
            ),
            takeaway="Same coherent task → continue. Different task → consider fresh.",
            sources=(COMMUNITY_SESSION_HYGIENE, ANTHROPIC_CONTEXT_ENGINEERING),
        ),
        Lesson(
            id="3.2",
            title="Continue vs fresh",
            objective="Apply the continue-vs-fresh decision to a concrete pair of tasks.",
            what=(
                "Current session: “Fix Dashboard bug.” New task: “Design a "
                "marketing website.” Should you continue in the same session?"
            ),
            quiz=(
                QuizQuestion(
                    prompt="Current session: fixing a Dashboard bug. New task: design a "
                    "marketing website. Continue or start fresh?",
                    options=(
                        QuizOption(
                            "Start fresh — the two tasks share no context", correct=True,
                        ),
                        QuizOption("Continue — more context is always better"),
                        QuizOption("It doesn't matter either way"),
                    ),
                    explanation=(
                        "These tasks are unrelated; carrying the Dashboard-bug history into "
                        "the marketing task adds nothing but noise."
                    ),
                ),
            ),
            takeaway="Unrelated tasks rarely benefit from shared history.",
            sources=(coach(),),
        ),
        Lesson(
            id="3.3",
            title="Long sessions",
            objective="Weigh continuity's value against accumulated irrelevant context.",
            what=(
                "Continuity has real value in a long, coherent task. But accumulated "
                "irrelevant context has a cost, whichever task produced it."
            ),
            why=(
                "Anthropic's guidance explicitly discusses compaction and starting fresh "
                "context windows for long-running work — this isn't unique to any one tool."
            ),
            better_approach=(
                "Use structured progress or hand-off notes so continuity doesn't depend on "
                "keeping everything in the conversation itself."
            ),
            takeaway=(
                "Compact when continuation is useful; start fresh when the history itself "
                "no longer is."
            ),
            sources=(ANTHROPIC_CONTEXT_ENGINEERING,),
        ),
    ),
)

LEVEL_4 = Level(
    id="4",
    title="Compaction",
    lessons=(
        Lesson(
            id="4.1",
            title="What /compact is for",
            objective="Describe compaction as summarization, not a reset.",
            what=(
                "Compaction takes a conversation nearing its context limit, summarizes it, "
                "and continues with that condensed summary instead of the full history."
            ),
            why="It's for continuing work while reducing older detail — not a magic reset.",
            takeaway="Compact continues the same task with less baggage; it doesn't erase it.",
            sources=(ANTHROPIC_CONTEXT_ENGINEERING,),
        ),
        Lesson(
            id="4.2",
            title="When to compact",
            objective="Choose between compacting and starting fresh for a given situation.",
            what=(
                "Long coherent task with useful history → compact. Different task, or old "
                "context no longer useful → fresh session."
            ),
            quiz=(
                QuizQuestion(
                    prompt="You're 40 turns into the same migration and context is "
                    "getting noisy, but the history is still relevant. Compact or fresh?",
                    options=(
                        QuizOption("Compact", correct=True),
                        QuizOption("Fresh session"),
                        QuizOption("Neither — just keep going"),
                    ),
                    explanation=(
                        "The task is still coherent and the history still matters — "
                        "compaction keeps that while trimming bulk."
                    ),
                ),
            ),
            takeaway="Compact for continuity with less noise; go fresh when history isn't useful.",
            sources=(ANTHROPIC_CONTEXT_ENGINEERING,),
        ),
        Lesson(
            id="4.3",
            title="How to make compaction useful",
            objective="Name what's worth preserving across a compaction.",
            what=(
                "Preserve the current objective, files changed, unresolved problems, "
                "failing tests, decisions made, and next steps."
            ),
            why=(
                "A community pattern is writing this out as an explicit progress file so it "
                "survives independently of the conversation's own summary."
            ),
            better_approach=(
                "Anthropic's own guidance notes you can steer what a compaction keeps — "
                "for example, telling it to always preserve the list of modified files and "
                "test commands."
            ),
            takeaway="Compaction is only as useful as what you make sure survives it.",
            sources=(COMMUNITY_SESSION_HYGIENE, ANTHROPIC_CONTEXT_ENGINEERING),
        ),
    ),
)
