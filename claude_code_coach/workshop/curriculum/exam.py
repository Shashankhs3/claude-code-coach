"""Level 20 — Final Exam. One lesson, many scenario-based questions,
covering every level. Passing requires 80% rather than every question, to
allow for one or two honest misses on a 20-question exam."""

from __future__ import annotations

from ..models import Level, Lesson, QuizOption, QuizQuestion
from .sources import coach

_QUESTIONS = (
    QuizQuestion(
        prompt='"Fix my project." What\'s the main problem with this prompt?',
        options=(
            QuizOption("It's too polite"),
            QuizOption("It gives Claude no starting point", correct=True),
            QuizOption("It's too long"),
        ),
        explanation="No goal, scope, or location — nothing to act on yet.",
    ),
    QuizQuestion(
        prompt="Which of these is part of Claude's context right now?",
        options=(
            QuizOption("Only your latest message"),
            QuizOption("Your prompt, conversation history, files read, and tool results",
                       correct=True),
        ),
        explanation="Context accumulates from the whole session, not just the last message.",
    ),
    QuizQuestion(
        prompt="You need to find one specific error in a huge log file. Best first move?",
        options=(
            QuizOption("Dump the entire file into the conversation"),
            QuizOption("Search for the relevant error, then inspect nearby lines",
                       correct=True),
        ),
        explanation="Targeted inspection avoids polluting context with irrelevant output.",
    ),
    QuizQuestion(
        prompt="You just finished a Dashboard bug fix. Next task: design a marketing page. "
        "Continue the session or start fresh?",
        options=(
            QuizOption("Start fresh — the tasks are unrelated", correct=True),
            QuizOption("Continue — more history is always better"),
        ),
        explanation="Unrelated tasks rarely benefit from shared history.",
    ),
    QuizQuestion(
        prompt="Long, coherent task, still relevant history, but context is getting full. "
        "Compact or fresh?",
        options=(
            QuizOption("Compact", correct=True),
            QuizOption("Fresh session"),
        ),
        explanation="The task is still coherent and the history still matters — compact, don't discard it.",
    ),
    QuizQuestion(
        prompt="A session has drifted across three unrelated tasks. Compact or fresh?",
        options=(
            QuizOption("Compact — summarize all three together"),
            QuizOption("Fresh — the old context isn't useful for any single task now",
                       correct=True),
        ),
        explanation="Compaction helps a coherent task; a tangle of unrelated tasks is better left behind.",
    ),
    QuizQuestion(
        prompt="Which belongs in CLAUDE.md?",
        options=(
            QuizOption("A bash command Claude can't guess, used in every session",
                       correct=True),
            QuizOption("A one-time note about today's specific bug"),
        ),
        explanation="CLAUDE.md is for what applies broadly and every session, not one-off notes.",
    ),
    QuizQuestion(
        prompt="Your CLAUDE.md has grown to 40 pages and Claude keeps missing rules in it. "
        "What's happening?",
        options=(
            QuizOption("Nothing — longer is always more thorough"),
            QuizOption("It's bloated — important rules are getting lost in the noise",
                       correct=True),
        ),
        explanation="A bloated CLAUDE.md causes Claude to effectively ignore parts of it.",
    ),
    QuizQuestion(
        prompt="You've now manually repeated the same 6-step release checklist five times. "
        "What should this become?",
        options=(
            QuizOption("A Skill", correct=True),
            QuizOption("A longer prompt each time"),
        ),
        explanation="A Skill packages a workflow you'd otherwise keep re-explaining.",
    ),
    QuizQuestion(
        prompt='The Coach labels a Skill candidate "INFERRED." What does that mean?',
        options=(
            QuizOption("The Skill already exists as a file on disk"),
            QuizOption("It's a pattern-based suggestion — no actual resource was found",
                       correct=True),
        ),
        explanation="INFERRED means a heuristic suspects it, not that a scan confirmed it.",
    ),
    QuizQuestion(
        prompt="You need to investigate three independent modules. Each investigation can "
        "run without the others. Best approach?",
        options=(
            QuizOption("Put all three into one giant prompt"),
            QuizOption("Read every file yourself sequentially"),
            QuizOption("Use appropriate independent subagent or parallel work", correct=True),
            QuizOption("Add everything to CLAUDE.md"),
        ),
        explanation="Independent workstreams can be delegated or parallelized.",
    ),
    QuizQuestion(
        prompt="You need to rename one variable in one file. Should you delegate this to a subagent?",
        options=(
            QuizOption("No — the overhead of delegation isn't worth it here", correct=True),
            QuizOption("Yes — always delegate to protect your own context"),
        ),
        explanation="Simple, small, sequential edits don't need isolation.",
    ),
    QuizQuestion(
        prompt="Claude needs to query a database it currently has no way to reach. What's the fit?",
        options=(
            QuizOption("An MCP server that connects to that database", correct=True),
            QuizOption("A longer prompt describing the database"),
        ),
        explanation="Reaching an external system is exactly what MCP is for.",
    ),
    QuizQuestion(
        prompt="Does connecting more MCP servers automatically make Claude more effective?",
        options=(
            QuizOption("Yes, unconditionally"),
            QuizOption("No — each one adds context and decision overhead too", correct=True),
        ),
        explanation="More tools mean more to choose between, not a free capability boost.",
    ),
    QuizQuestion(
        prompt='You want linting to run after every single file edit, with zero exceptions. '
        "What's the right mechanism?",
        options=(
            QuizOption("A hook", correct=True),
            QuizOption("A note in CLAUDE.md asking nicely"),
        ),
        explanation="A hook is deterministic; a CLAUDE.md instruction is only advisory.",
    ),
    QuizQuestion(
        prompt='Claude says a change is "done." What should you ask for before trusting that?',
        options=(
            QuizOption("Nothing — trust the assertion"),
            QuizOption("Evidence: a test run, a diff, or a screenshot", correct=True),
        ),
        explanation="Without a check, \"looks done\" is the only signal — evidence closes the loop.",
    ),
    QuizQuestion(
        prompt="You're about to let Claude run unattended on a task that could touch "
        "production systems. What matters most?",
        options=(
            QuizOption("Appropriate permission boundaries for what it can actually reach",
                       correct=True),
            QuizOption("Nothing — unattended mode is always fine"),
        ),
        explanation="Autonomy without matching constraints is exactly the risk least-privilege addresses.",
    ),
    QuizQuestion(
        prompt="Two sub-tasks depend on each other's results. Should they run in parallel?",
        options=(
            QuizOption("Yes — parallel is always faster"),
            QuizOption("No — dependent work needs to run in sequence", correct=True),
        ),
        explanation="Parallelism suits independent work, not work with a real dependency order.",
    ),
    QuizQuestion(
        prompt='"Give me a complete explanation of every file" vs "tell me which files are '
        'relevant and why" — which is better scoped output?',
        options=(
            QuizOption("The complete-explanation request"),
            QuizOption("The relevant-files request", correct=True),
        ),
        explanation="Ask for exactly what you need, not an exhaustive dump you'll filter yourself.",
    ),
    QuizQuestion(
        prompt='"A shorter prompt always costs fewer tokens overall." Is this accurate?',
        options=(
            QuizOption("Yes, always"),
            QuizOption(
                "Not necessarily — a clearer, possibly longer prompt can reduce wasted "
                "exploration and rework", correct=True,
            ),
        ),
        explanation="Total cost includes rework caused by ambiguity, not just prompt length.",
    ),
    QuizQuestion(
        prompt="Task: rename a button label. How much context does this need?",
        options=(
            QuizOption(
                "Minimal, targeted context is appropriate here — the task is small",
                correct=True,
            ),
            QuizOption("The entire repository, to be safe"),
        ),
        explanation="Context efficiency means matching context to the job — this job is small.",
    ),
)

LEVEL_20 = Level(
    id="20",
    title="Final Exam",
    lessons=(
        Lesson(
            id="20.1",
            title="Final exam",
            objective="Apply every decision from this course to fresh scenarios.",
            what=(
                f"{len(_QUESTIONS)} scenario-based questions covering prompts, context, "
                "search, sessions, compaction, fresh sessions, CLAUDE.md, Skills, Agents, "
                "MCP, hooks, verification, permissions, parallel work, tool output, and "
                "context or token misconceptions."
            ),
            why="These test decisions, not memorized definitions.",
            quiz=_QUESTIONS,
            passing_ratio=0.8,
            takeaway="Passing this exam means you can make these calls on a real task, not "
                     "just recite the rules.",
            sources=(coach("Exam questions are original scenarios written for this course, "
                            "grounded in the sources cited throughout it."),),
        ),
    ),
)
