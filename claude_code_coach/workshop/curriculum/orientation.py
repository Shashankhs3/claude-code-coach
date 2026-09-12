"""Level 0 (Orientation) and Level 1 (Prompt Fundamentals)."""

from __future__ import annotations

from ..models import Level, Lesson, QuizOption, QuizQuestion, TryIt
from .sources import ANTHROPIC_CONTEXT_ENGINEERING, CLAUDE_CODE_BEST_PRACTICES, coach

LEVEL_0 = Level(
    id="0",
    title="Orientation",
    lessons=(
        Lesson(
            id="0.1",
            title="What Claude Code actually is",
            objective="Describe Claude Code as an agentic loop, not a chat window.",
            what=(
                "Claude Code is an agentic coding environment: a conversation loop where "
                "Claude can reason, choose tools, read and search your files, run shell "
                "commands, and make edits — not just answer a question and stop."
            ),
            why=(
                "Every tool call and its result becomes part of the working context for the "
                "next step. Understanding that loop is what makes the rest of this course "
                "make sense — context, sessions, compaction, and delegation are all just "
                "ways of managing what flows through it."
            ),
            example=(
                "You\n → Prompt\n → Claude reasons and chooses tools\n → Read / Search / "
                "Edit / Bash / …\n → Results return to context\n → Next step"
            ),
            takeaway=(
                "Claude Code works in a loop of reasoning and tool use, and everything that "
                "loop produces becomes context for what comes next."
            ),
            sources=(CLAUDE_CODE_BEST_PRACTICES,),
        ),
        Lesson(
            id="0.2",
            title='What "context" means',
            objective="Define context as everything Claude currently has to work with.",
            what=(
                "Context is everything Claude can see to do the current job: your "
                "instructions, project instructions, files it has read, prior tool results, "
                "the conversation so far, and anything it has already produced."
            ),
            why=(
                "Context isn't free just because it's available — irrelevant material "
                "sitting in context can crowd out what actually matters to the task at hand."
            ),
            better_approach=(
                "Official guidance treats context management as a central concern in "
                "long-running agentic work, not an afterthought — the same way you'd manage "
                "a whiteboard's limited space in a long meeting."
            ),
            quiz=(
                QuizQuestion(
                    prompt="Which of these is part of Claude's context for the current step?",
                    options=(
                        QuizOption("Only the exact sentence you just typed"),
                        QuizOption(
                            "Your prompt, prior conversation, files read, and tool results "
                            "so far", correct=True,
                        ),
                        QuizOption("Nothing until you explicitly attach a file"),
                    ),
                    explanation=(
                        "Context accumulates from everything the session has done, not just "
                        "the latest message."
                    ),
                ),
            ),
            takeaway="Context is the full working set, not just your latest message.",
            sources=(ANTHROPIC_CONTEXT_ENGINEERING,),
        ),
        Lesson(
            id="0.3",
            title='Context is not the same as "tokens used"',
            objective="Distinguish context size from token billing and cache behavior.",
            what=(
                "Context size, input tokens, output tokens, cache behavior, tool activity, "
                "and reasoning are related but distinct. Growing context can affect focus "
                "and quality well before it becomes a billing concern, and the two shouldn't "
                "be conflated."
            ),
            why=(
                "This course will not claim to know your exact token cost from local "
                "heuristics — the Coach can observe patterns in your local activity, but it "
                "cannot see Anthropic's actual billing or internal token accounting."
            ),
            takeaway=(
                "Manage context for focus and relevance first; don't assume you know exact "
                "billing math from a local estimate."
            ),
            sources=(coach("Distinguishing context health from billing is a Coach framing, "
                            "not a documented Anthropic metric."),),
        ),
    ),
)

LEVEL_1 = Level(
    id="1",
    title="Prompt Fundamentals",
    lessons=(
        Lesson(
            id="1.1",
            title="The anatomy of a good coding task",
            objective="Describe a task in terms of intent, context, boundaries, and outcome.",
            what="Intent, relevant context, boundaries, and the expected outcome.",
            why=(
                "These four things reduce ambiguity — they are not a rigid template every "
                "prompt must follow word for word."
            ),
            better_approach=(
                "Current Anthropic guidance recommends clarity, directness, specificity, and "
                "relevant context over any particular fixed phrasing."
            ),
            takeaway="Good prompts reduce ambiguity, not necessarily length.",
            sources=(CLAUDE_CODE_BEST_PRACTICES,),
        ),
        Lesson(
            id="1.2",
            title="Underspecified vs over-specified",
            objective="Recognize both too little and too much direction in a prompt.",
            what=(
                "Two failure modes: giving Claude nothing to go on, and micromanaging every "
                "step when Claude could reasonably determine the sequence itself."
            ),
            why="Both waste effort — one on guessing, the other on unnecessary control.",
            example='"Fix my project."',
            bad_approach=(
                '"Fix my project." — no starting point at all.\n\nThe opposite extreme: '
                '"Read these 17 files in this exact order, then run these 11 commands, '
                'then…" when Claude could work out an efficient sequence itself.'
            ),
            better_approach=(
                '"Fix the login timeout in the authentication flow. Inspect the relevant '
                'implementation and tests. Make the smallest necessary change and verify it."'
            ),
            quiz=(
                QuizQuestion(
                    prompt="What's the problem with dictating an exact 17-file reading order?",
                    options=(
                        QuizOption("Nothing — more direction is always better"),
                        QuizOption(
                            "It micromanages execution Claude could reasonably figure out "
                            "itself", correct=True,
                        ),
                        QuizOption("Claude can only read files in alphabetical order"),
                    ),
                    explanation=(
                        "Give direction where judgment matters; avoid micromanaging "
                        "execution unnecessarily."
                    ),
                ),
            ),
            takeaway="Give direction where judgment matters; don't micromanage execution.",
            sources=(CLAUDE_CODE_BEST_PRACTICES,),
        ),
        Lesson(
            id="1.3",
            title="Prompt rewrite lab",
            objective="Use the Coach's own analyzer to see what a real prompt is missing.",
            what=(
                "Enter a real task prompt below. The Coach's deterministic analyzer — the "
                "same one behind the Prompt Inspector — will show what's missing, what's "
                "unnecessary, and a suggested rewrite."
            ),
            why=(
                "This lab uses the existing rule-based Coach analyzer, not an LLM grading "
                "your prompt — the same scoring you'd get on the Prompt Inspector page."
            ),
            try_it=TryIt(
                instructions="Type a task prompt above and press Analyze to see the breakdown.",
                related_page="Prompt Inspector",
                action_label="Open the full Prompt Inspector",
            ),
            takeaway="A concrete rewrite, grounded in a real analyzer, teaches more than a rule.",
            sources=(coach("Prompt Inspector's deterministic scoring, reused here."),),
            interactive="prompt_lab",
        ),
    ),
)
