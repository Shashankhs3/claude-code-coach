"""Level 7 (Agents/Subagents), Level 8 (Tools), Level 9 (MCP)."""

from __future__ import annotations

from ..models import Level, Lesson, QuizOption, QuizQuestion, TryIt
from .sources import CLAUDE_CODE_MCP, CLAUDE_CODE_SUBAGENTS, coach

LEVEL_7 = Level(
    id="7",
    title="Agents / Subagents",
    lessons=(
        Lesson(
            id="7.1",
            title="What a subagent is",
            objective="Describe a subagent as an isolated worker that reports back a summary.",
            what=(
                "An independent worker operating in its own separate context for a "
                "delegated task — it doesn't see your main conversation's history, and only "
                "its summary comes back to you."
            ),
            why=(
                "Documented guidance recommends subagents for parallel or independent work, "
                "and explicitly warns that models can overuse them for things that didn't "
                "need delegating."
            ),
            takeaway="A subagent trades isolation for a distilled summary, not full detail.",
            sources=(CLAUDE_CODE_SUBAGENTS,),
        ),
        Lesson(
            id="7.2",
            title="When to use an Agent",
            objective="Match agent delegation to genuinely independent work.",
            what=(
                "Broad investigation, independent module analysis, isolated research, "
                "parallel workstreams, and tasks that don't need the main context "
                "continuously."
            ),
            takeaway="Good agent candidates are self-contained enough to return just a summary.",
            sources=(CLAUDE_CODE_SUBAGENTS,),
        ),
        Lesson(
            id="7.3",
            title="When NOT to use an Agent",
            objective="Recognize when delegating adds overhead instead of saving it.",
            what=(
                "Simple questions, one-file edits, sequential tasks, and work where the "
                "main context is needed continuously."
            ),
            why="Documented guidance explicitly cautions against overusing subagents for "
                "simple tasks — delegation itself has overhead.",
            quiz=(
                QuizQuestion(
                    prompt="You need to rename one variable in one file. Delegate to a subagent?",
                    options=(
                        QuizOption("No — this is a small, sequential edit", correct=True),
                        QuizOption("Yes — always delegate to save your own context"),
                    ),
                    explanation="Delegation overhead isn't worth it for a small, one-file edit.",
                ),
            ),
            takeaway="Not every task benefits from delegation — some are just faster directly.",
            sources=(CLAUDE_CODE_SUBAGENTS,),
        ),
        Lesson(
            id="7.4",
            title="Parallelism",
            objective="Tell independent work apart from work with a real dependency order.",
            what="Independent tasks can run in parallel; dependent tasks need to run in sequence.",
            why=(
                "Current prompting guidance discusses parallel tool calls specifically for "
                "operations that don't depend on each other's results."
            ),
            quiz=(
                QuizQuestion(
                    prompt="Three independent modules need investigation, each unrelated to "
                    "the others. Best approach?",
                    options=(
                        QuizOption("One giant prompt covering all three"),
                        QuizOption("Read every file yourself, one at a time"),
                        QuizOption(
                            "Independent subagents / parallel work, one per module",
                            correct=True,
                        ),
                        QuizOption("Add all three to CLAUDE.md"),
                    ),
                    explanation="Independent workstreams are exactly what delegation or "
                    "parallelism is for.",
                ),
            ),
            takeaway="Independent work → parallel. Dependent work → sequential.",
            sources=(CLAUDE_CODE_SUBAGENTS,),
        ),
    ),
)

LEVEL_8 = Level(
    id="8",
    title="Tools",
    lessons=(
        Lesson(
            id="8.1",
            title="Claude chooses tools",
            objective="Trust tool selection (Search, Read, Edit, Bash, …) without "
                       "micromanaging it.",
            what="Search, Read, Edit, Write, Bash, and more — Claude selects which to use.",
            why="Micromanaging every individual tool call adds overhead without adding value.",
            takeaway="Direct the outcome; let Claude choose the specific tool calls.",
            sources=(coach(),),
        ),
        Lesson(
            id="8.2",
            title="Search tools vs reading",
            objective="Prefer finding first over dumping everything.",
            what="Find the relevant location first, then inspect it — rather than dumping everything.",
            takeaway="Find first, then inspect — the same search-first pattern from Level 2.",
            sources=(coach(),),
        ),
        Lesson(
            id="8.3",
            title="Output control",
            objective="Ask for the output you actually need, not an exhaustive dump.",
            what="Ask only for the output you actually need.",
            bad_approach='"Give me a complete explanation of every file."',
            better_approach='"Tell me which files are relevant and why."',
            quiz=(
                QuizQuestion(
                    prompt="Which request is better scoped?",
                    options=(
                        QuizOption('"Give me a complete explanation of every file."'),
                        QuizOption('"Tell me which files are relevant and why."', correct=True),
                    ),
                    explanation="The second asks for exactly what's needed, not an exhaustive dump.",
                ),
            ),
            takeaway="Ask for exactly what you need, not everything Claude could say.",
            sources=(coach(),),
        ),
    ),
)

LEVEL_9 = Level(
    id="9",
    title="MCP / External Capabilities",
    lessons=(
        Lesson(
            id="9.1",
            title="What MCP is",
            objective="Describe MCP as a bridge to external systems and capabilities.",
            what="Claude Code → MCP → an external capability or system.",
            why="MCP is how Claude reaches things outside your files and shell — a database, "
                "an issue tracker, a design tool.",
            takeaway="MCP connects Claude to capabilities beyond file edits and shell commands.",
            sources=(CLAUDE_CODE_MCP,),
        ),
        Lesson(
            id="9.2",
            title="When MCP is useful",
            objective="Identify tasks that genuinely need an external capability.",
            what="External system access, a domain-specific capability, or information not "
                 "otherwise available.",
            try_it=TryIt(
                instructions="See what's actually connected before assuming Claude can't do something.",
                related_page="Integrations",
            ),
            takeaway="Check what's actually connected before assuming a capability is missing.",
            sources=(CLAUDE_CODE_MCP,),
        ),
        Lesson(
            id="9.3",
            title="Don't install MCP for everything",
            objective="Weigh a new tool's complexity and context cost against its actual "
                       "benefit.",
            what="More tools are not automatically better.",
            why="Additional tools can add complexity, context, and decision overhead.",
            better_approach="Only use approved, currently-connected capabilities — never assume "
                            "or invent an MCP server that isn't actually configured.",
            quiz=(
                QuizQuestion(
                    prompt="Does adding more MCP servers automatically make Claude more capable?",
                    options=(
                        QuizOption("Yes, always"),
                        QuizOption(
                            "No — each one adds complexity and decision overhead too",
                            correct=True,
                        ),
                    ),
                    explanation="More tools mean more to choose between, not a free capability boost.",
                ),
            ),
            takeaway="Add MCP capabilities deliberately, not by default.",
            sources=(CLAUDE_CODE_MCP,),
        ),
    ),
)
