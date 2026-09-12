"""Level 10 (Hooks), Level 11 (Permissions/Safety), Level 12 (Verification)."""

from __future__ import annotations

from ..models import Level, Lesson, QuizOption, QuizQuestion
from .sources import CLAUDE_CODE_BEST_PRACTICES, CLAUDE_CODE_HOOKS, CLAUDE_CODE_PERMISSIONS, coach

LEVEL_10 = Level(
    id="10",
    title="Hooks",
    lessons=(
        Lesson(
            id="10.1",
            title="What hooks are",
            objective="Describe a hook as a deterministic reaction to a lifecycle event.",
            what=(
                "Hooks are commands that run automatically at specific points in Claude "
                "Code's lifecycle — for example around a tool being used, a file being "
                "edited, or a session starting."
            ),
            why=(
                "Unlike an instruction in CLAUDE.md, which Claude follows advisedly, a hook "
                "runs deterministically — it happens every time, with zero exceptions."
            ),
            takeaway="A hook guarantees an action happens; an instruction only asks for it.",
            sources=(CLAUDE_CODE_HOOKS,),
        ),
        Lesson(
            id="10.2",
            title="What hooks are good for",
            objective="Identify tasks that benefit from a guaranteed, deterministic reaction.",
            what="Policy checks, automation, logging, validation, and workflow integration.",
            example='"Run the linter after every file edit" or "block writes to the migrations folder."',
            takeaway="Reach for a hook when an action must happen every time, without exception.",
            sources=(CLAUDE_CODE_HOOKS,),
        ),
        Lesson(
            id="10.3",
            title="Hooks vs Skills vs Agents",
            objective="Tell apart the five main customization mechanisms by what each one is.",
            what=(
                "Hook = reacts to a lifecycle event, deterministically.\n"
                "Skill = a reusable, on-demand workflow or expertise package.\n"
                "Agent = a delegated, independent worker in its own context.\n"
                "CLAUDE.md = persistent, always-loaded project instruction.\n"
                "Prompt = task-specific intent, for right now."
            ),
            why="This distinction is central to the whole course — most workflow-strategy "
                "questions come down to picking the right one of these five.",
            quiz=(
                QuizQuestion(
                    prompt='"This rule must be enforced with zero exceptions, every time." '
                    "Which mechanism fits?",
                    options=(
                        QuizOption("Hook", correct=True),
                        QuizOption("Skill"),
                        QuizOption("CLAUDE.md"),
                    ),
                    explanation="Only a hook is deterministic — CLAUDE.md is advisory.",
                ),
            ),
            takeaway="Rule to enforce → hook. Contextual know-how → Skill. Delegation → Agent. "
                     "Always-on guidance → CLAUDE.md. This task → prompt.",
            sources=(coach("The decision framing across Hook/Skill/Agent/CLAUDE.md is a "
                            "Coach synthesis of documented mechanisms."),),
        ),
    ),
)

LEVEL_11 = Level(
    id="11",
    title="Permissions / Safety",
    lessons=(
        Lesson(
            id="11.1",
            title="Permissions and least privilege",
            objective="Explain why autonomous execution needs explicit approval boundaries.",
            what=(
                "Claude Code's permission modes control which actions can run without "
                "asking you first — from a mode that asks before every file write or "
                "command, up to one that runs everything unattended."
            ),
            why=(
                "More autonomy means less chance to catch a mistake before it happens — "
                "least privilege (only the access actually needed) applies to an agent the "
                "same way it applies to a person."
            ),
            example=(
                "Review every action yourself, auto-approve edits you're already reviewing, "
                "explore in a read-only planning mode, or run unattended inside an isolated "
                "environment — each trades convenience for oversight differently."
            ),
            quiz=(
                QuizQuestion(
                    prompt="You're about to let Claude run fully unattended for an hour on "
                    "a task touching production credentials. What matters most first?",
                    options=(
                        QuizOption(
                            "Appropriate permission boundaries and isolation for what it "
                            "can actually touch", correct=True,
                        ),
                        QuizOption("Nothing — unattended mode is always safe"),
                        QuizOption("Making the prompt shorter"),
                    ),
                    explanation=(
                        "Autonomous execution needs constraints matched to what's actually "
                        "at risk — never an unsafe bypass for convenience."
                    ),
                ),
            ),
            takeaway="Match the permission mode to what's actually at stake — never bypass "
                     "safety checks for convenience.",
            sources=(CLAUDE_CODE_PERMISSIONS,),
        ),
    ),
)

LEVEL_12 = Level(
    id="12",
    title="Verification",
    lessons=(
        Lesson(
            id="12.1",
            title="Implementation is not completion",
            objective="Treat a change as unfinished until it's actually checked.",
            what="Change → test → inspect diff → verify behavior.",
            why=(
                "Documented guidance is direct here: without something Claude can run to "
                "check its own work, \"looks done\" is the only signal available, and every "
                "mistake waits for you to notice it."
            ),
            takeaway="A change without a check is not yet a finished change.",
            sources=(CLAUDE_CODE_BEST_PRACTICES,),
        ),
        Lesson(
            id="12.2",
            title="Verification planning",
            objective="State what 'done' means before Claude starts, not after.",
            what='Tell Claude what "done" means up front: a test, a build, expected behavior.',
            bad_approach='"Implement a function that validates email addresses."',
            better_approach=(
                '"Write a validateEmail function. Example cases: user@example.com is true, '
                '\'invalid\' is false, user@.com is false. Run the tests after implementing."'
            ),
            quiz=(
                QuizQuestion(
                    prompt="Which prompt makes verification easiest to close the loop on?",
                    options=(
                        QuizOption('"Implement a function that validates email addresses."'),
                        QuizOption(
                            '"…Example cases: […] Run the tests after implementing."',
                            correct=True,
                        ),
                    ),
                    explanation=(
                        "Concrete verification criteria let Claude check its own work "
                        "instead of leaving \"done\" to guesswork."
                    ),
                ),
            ),
            takeaway="Give Claude a pass-or-fail check, not just a description of the goal.",
            sources=(CLAUDE_CODE_BEST_PRACTICES,),
        ),
    ),
)
