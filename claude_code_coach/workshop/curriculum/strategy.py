"""Level 13 (Workflow Strategy), Level 14 (Context Economics), Level 15
(Cost/Efficiency Myths), and Level 16 (Advanced Workflows)."""

from __future__ import annotations

from ..models import Level, Lesson, QuizOption, QuizQuestion, TryIt
from .sources import ANTHROPIC_CONTEXT_ENGINEERING, ANTHROPIC_LONG_RUNNING_AGENTS, coach

LEVEL_13 = Level(
    id="13",
    title="Workflow Strategy",
    lessons=(
        Lesson(
            id="13.1",
            title="Choose the right approach",
            objective="Route a task to the right mechanism using one decision tree.",
            what=(
                "One simple task → Prompt. Repeated workflow → Skill. Independent "
                "investigation → Agent. Stable project rule → CLAUDE.md. External "
                "capability → MCP. Noisy context → Compact / Fresh. Independent "
                "workstreams → Parallel."
            ),
            why="This is the same judgment the Approach Advisor makes on a real task of yours.",
            try_it=TryIt(
                instructions="Describe a real task and see the Coach's own recommended approach.",
                related_page="Approach Advisor",
            ),
            takeaway="Every earlier level was really building toward this one decision tree.",
            sources=(coach("The decision tree mirrors the Approach Advisor's own logic."),),
        ),
    ),
)

LEVEL_14 = Level(
    id="14",
    title="Context Economics",
    lessons=(
        Lesson(
            id="14.1",
            title="What consumes context",
            objective="List the real components that make up working context.",
            what=(
                "Prompt + history + files + tool results + instructions + agent activity + "
                "outputs — all of it, not just what you typed."
            ),
            why=(
                "Efficiency is about relevant context and an appropriate workflow, not "
                "merely typing fewer words."
            ),
            takeaway="Context is a sum of many sources — the prompt is only one of them.",
            sources=(ANTHROPIC_CONTEXT_ENGINEERING,),
        ),
        Lesson(
            id="14.2",
            title="High-value vs low-value context",
            objective="Classify concrete examples of context as high- or low-value for a task.",
            what="Classify each of these as high-value or low-value context for a bug fix.",
            quiz=(
                QuizQuestion(
                    prompt="The relevant architecture file for the module you're fixing:",
                    options=(
                        QuizOption("High value", correct=True),
                        QuizOption("Low value"),
                    ),
                    explanation="Directly relevant to the task — worth the context it costs.",
                ),
                QuizQuestion(
                    prompt="A massive unrelated log file from a different subsystem:",
                    options=(
                        QuizOption("High value"),
                        QuizOption("Low value", correct=True),
                    ),
                    explanation="Unrelated bulk content that doesn't serve the current task.",
                ),
                QuizQuestion(
                    prompt="The exact failing test for the bug you're fixing:",
                    options=(
                        QuizOption("High value", correct=True),
                        QuizOption("Low value"),
                    ),
                    explanation="Directly diagnostic for the task at hand.",
                ),
                QuizQuestion(
                    prompt="500 lines of unrelated generated output from an earlier, "
                    "different task in the same session:",
                    options=(
                        QuizOption("High value"),
                        QuizOption("Low value", correct=True),
                    ),
                    explanation="Leftover from unrelated work — a candidate for /clear, not "
                                "something worth keeping around.",
                ),
            ),
            takeaway="Value is about relevance to the current task, not size or recency alone.",
            sources=(coach(),),
        ),
        Lesson(
            id="14.3",
            title="Context efficiency patterns",
            objective="Recall the recurring set of habits that keep context relevant.",
            what=(
                "Search before reading broadly. Inspect targeted regions. Request concise "
                "outputs. Use reusable instructions for recurring rules. Delegate isolated "
                "investigations. Separate unrelated tasks. Compact when continuing matters. "
                "Start fresh when old context doesn't."
            ),
            takeaway="These eight patterns are the practical summary of everything so far.",
            sources=(ANTHROPIC_CONTEXT_ENGINEERING,),
        ),
        Lesson(
            id="14.4",
            title="Context efficiency ≠ minimum context",
            objective="Recognize that the 'right' amount of context depends on the task's scope.",
            what=(
                "Task A: “Rename a button.” Minimal relevant context is good here.\n\n"
                "Task B: “Understand the architecture before a major migration.” Broad "
                "repository context can be justified here."
            ),
            why="This is the central principle of the whole course: use the right amount of "
                "context for the job, not always the smallest possible amount.",
            quiz=(
                QuizQuestion(
                    prompt='Task: "Understand the architecture before a major migration." '
                    "Is broad repository reading justified?",
                    options=(
                        QuizOption("Yes — the task itself needs broad understanding",
                                   correct=True),
                        QuizOption("No — always minimize context regardless of the task"),
                    ),
                    explanation=(
                        "Context efficiency means matching context to the job, not "
                        "minimizing it unconditionally."
                    ),
                ),
            ),
            takeaway="Use the right amount of context for the job — not always the least.",
            sources=(coach("Central product principle of this course."),),
        ),
    ),
)

LEVEL_15 = Level(
    id="15",
    title="Cost / Efficiency Myths",
    lessons=(
        Lesson(
            id="15.1",
            title="Myth vs reality",
            objective="Replace five common efficiency misconceptions with the more accurate view.",
            what=(
                "Myth: a shorter prompt always means fewer tokens overall.\n"
                "Reality: a clearer prompt can reduce wasted exploration and rework, even if "
                "it's longer.\n\n"
                "Myth: never let Claude read many files.\n"
                "Reality: broad reading can be correct for a genuinely broad task.\n\n"
                "Myth: always use a subagent to save tokens.\n"
                "Reality: subagents help isolated, independent work; unnecessary delegation "
                "adds its own overhead.\n\n"
                "Myth: put everything in CLAUDE.md so Claude knows everything.\n"
                "Reality: persistent instructions should be useful and lean — excessive "
                "always-loaded material becomes a burden, not a help.\n\n"
                "Myth: /compact fixes everything.\n"
                "Reality: compaction helps when continuing the same task; a fresh session "
                "can be cleaner for a genuinely new one."
            ),
            quiz=(
                QuizQuestion(
                    prompt='"Shorter prompts always cost fewer tokens overall." True or reality-checked?',
                    options=(
                        QuizOption("True as stated"),
                        QuizOption(
                            "A clearer (possibly longer) prompt can reduce wasted "
                            "exploration and rework", correct=True,
                        ),
                    ),
                    explanation="Total cost includes rework from ambiguity, not just the prompt's length.",
                ),
                QuizQuestion(
                    prompt='"Never let Claude read many files." True or reality-checked?',
                    options=(
                        QuizOption("True as stated"),
                        QuizOption("Broad reading can be correct for a genuinely broad task",
                                   correct=True),
                    ),
                    explanation="It depends on whether the task itself is broad.",
                ),
                QuizQuestion(
                    prompt='"Always use a subagent to save tokens." True or reality-checked?',
                    options=(
                        QuizOption("True as stated"),
                        QuizOption(
                            "Subagents help isolated work; unnecessary delegation adds "
                            "overhead", correct=True,
                        ),
                    ),
                    explanation="Delegation isn't free — it's a good fit for some tasks, not all.",
                ),
                QuizQuestion(
                    prompt='"Put everything in CLAUDE.md so Claude knows everything." True '
                    "or reality-checked?",
                    options=(
                        QuizOption("True as stated"),
                        QuizOption(
                            "Excessive always-loaded material becomes a burden, not a help",
                            correct=True,
                        ),
                    ),
                    explanation="A bloated CLAUDE.md causes Claude to miss the rules that matter.",
                ),
                QuizQuestion(
                    prompt='"/compact fixes everything." True or reality-checked?',
                    options=(
                        QuizOption("True as stated"),
                        QuizOption(
                            "It helps when continuing the same task; a fresh session can be "
                            "cleaner for a new one", correct=True,
                        ),
                    ),
                    explanation="Compaction isn't a universal fix — it's the right tool for a specific situation.",
                ),
            ),
            takeaway="Every one of these myths collapses the same way: it treats a situational "
                     "trade-off as a universal rule.",
            sources=(coach("Myth/reality framing is a Coach synthesis of the documented "
                            "guidance cited throughout this course."),),
        ),
    ),
)

LEVEL_16 = Level(
    id="16",
    title="Advanced Workflows",
    lessons=(
        Lesson(
            id="16.1",
            title="Long-horizon projects",
            objective="Plan a project that will outlast a single context window.",
            what="Progress files, structured TODO state, verification, and context transitions.",
            why="Official guidance on long-running agents covers exactly this: how to keep "
                "work coherent across more than one context window.",
            takeaway="Plan for the transition between context windows, not just the current one.",
            sources=(ANTHROPIC_LONG_RUNNING_AGENTS,),
        ),
        Lesson(
            id="16.2",
            title="Multiple context windows",
            objective="Describe the work → save → transition → reload → continue cycle.",
            what="Work → save state → compact or fresh → reload state → continue.",
            takeaway="A saved, explicit state is what makes crossing a context boundary safe.",
            sources=(ANTHROPIC_CONTEXT_ENGINEERING,),
        ),
        Lesson(
            id="16.3",
            title="Parallel sessions",
            objective="Decide when independent workstreams justify separate sessions.",
            what="Independent workstreams → separate sessions.",
            why="Avoid parallelism when the work is sequentially dependent — splitting "
                "dependent steps apart just adds coordination overhead.",
            takeaway="Parallel sessions help independent work; dependent work stays sequential.",
            sources=(coach(),),
        ),
    ),
)
