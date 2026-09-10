"""Regex/keyword signals shared by the task classifier and dimension analyzers.

Centralized here so tuning the heuristics (per section 26 of the spec:
"continuously improve the heuristics") means editing one file, not hunting
through every analyzer module.
"""

from __future__ import annotations

import re


def rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


QUESTION_START = rx(
    r"^(what|why|how|where|which|who|when|can you explain|"
    r"show me|tell me|is there|does|do you)\b"
)

# Imperative but still information-seeking: "Find where...", "Locate the...".
INFO_IMPERATIVE_START = rx(r"^(find|locate|identify|list|show)\b")

ACTION_VERBS = rx(
    r"\b(add|create|build|implement|modify|change|fix|refactor|remove|"
    r"update|delete|rewrite|migrate|debug|investigate|optimi[sz]e|"
    r"improve|review|audit|integrate|support)\b"
)

EXPLAIN_VERBS = rx(
    r"\b(explain|describe|walk me through|walk through|clarify|"
    r"what does .* do|how does .* work)\b"
)

INVESTIGATE_VERBS = rx(
    r"\b(investigate|trace|diagnose|reproduce|figure out why|track down)\b"
)

DEBUG_SIGNALS = rx(
    r"\b(bug|error|crash(es|ed|ing)?|exception|fails?|failing|failure|"
    r"broken|500|timeout|stack ?trace|regression|doesn'?t work|not working)\b"
)

IMPLEMENT_SIGNALS = rx(
    r"\b(implement|add (a |the )?(feature|support|endpoint|field|option)|"
    r"build (a |the )?new|create (a |the )?new|integrate)\b"
)

REFACTOR_SIGNALS = rx(
    r"\b(refactor|restructure|reorgani[sz]e|rename|extract|clean ?up|"
    r"simplify (the )?code|de-?duplicate)\b"
)

REVIEW_SIGNALS = rx(
    r"\b(review|audit|assess)\b|"
    r"\bcheck\b.{0,40}\bfor\b.{0,30}\b(issues?|problems?|bugs?|vulnerab\w*)\b|"
    r"\binspect\b.{0,40}\bfor\b"
)

# Action verbs that appear only inside a negated/constraint phrase
# ("don't modify anything") shouldn't count as an implementation request.
NEGATED_ACTION = rx(
    r"\b(don'?t|do not|never|without|shouldn'?t|should not|must not|avoid)\b"
    r"(\s+\w+){0,2}\s+"
    r"(add\w*|creat\w*|build\w*|implement\w*|modify\w*|modif\w*|chang\w*|"
    r"fix\w*|refactor\w*|remov\w*|updat\w*|delet\w*|rewrit\w*|migrat\w*|"
    r"debug\w*|investigat\w*|optimi[sz]\w*|improv\w*|review\w*|audit\w*|"
    r"integrat\w*|support\w*)\b"
)

SECURITY_SIGNALS = rx(
    r"\b(security|vulnerab\w*|injection|xss|csrf|sanitiz\w*|encrypt\w*|"
    r"secrets?|auth(entication|orization)?|exploit|owasp|penetration)\b"
)

RESEARCH_SIGNALS = rx(
    r"\b(research|compare|evaluate|best way to|options for|alternatives|"
    r"pros and cons|which (library|approach|tool) should)\b"
)

REPETITIVE_TRIGGER = rx(
    r"\b(each time|every time|every pr\b|every pull request|"
    r"for every (pr|pull request|commit|release|endpoint|deployment|merge)|"
    r"always do|whenever (a|an|there))\b"
)

CHECKLIST_STEP_WORDS = rx(
    r"\b(first|then|finally|next|check|inspect|identify|produce|"
    r"validate|verify|confirm)\b"
)

PATH_PATTERN = rx(
    r"(^|[\s`'\"(])(src|app|lib|tests?|docs|packages?|components?|"
    r"services?|server|client|backend|frontend)[/\\]|"
    r"\b[\w./\\-]+\.(py|js|jsx|ts|tsx|java|go|rs|cs|cpp|c|sql|md|json|yaml|yml)\b"
)

SCOPE_LANGUAGE = rx(
    r"\b(only|just|focus on|within|under|related to|"
    r"affected|relevant)\b.{0,60}\b(code|files?|folder|directory|module|"
    r"package|component|auth|authentication|payment|checkout|api|"
    r"database|db|backend|frontend)\b"
)

SEARCH_VERBS = rx(
    r"\b(search|grep|find|locate|trace|inspect|investigate|reproduce|"
    r"look for|start by locating|check the relevant|first locate)\b"
)

BROAD_READ = rx(
    r"\b(entire|whole|all|every|everything|full)\s+"
    r"(repo|repository|project|codebase|files?|application|file)\b"
)

CONSTRAINT_WORDS = rx(
    r"\b(don'?t|do not|must not|should not|avoid|only modify|reuse|"
    r"smallest|minimal|without (touching|modifying|changing)|keep|preserve|"
    r"unrelated|existing conventions|production|read.?only|no changes?)\b"
)

DONE_WORDS = rx(
    r"\b(done when|complete when|success when|success criteria|"
    r"acceptance criteria|expected result|tests? pass|should pass|"
    r"verify that|confirm that|regression test)\b"
)

OUTPUT_WORDS = rx(
    r"\b(return only|output|give me|summari[sz]e|report|format|"
    r"top \d+|one sentence|bullet|table|checklist|severity)\b"
)

VAGUE_GOAL_PATTERNS = [
    rx(
        r"^\s*(fix|improve|change|update|clean up|make better)\s+(my|the)\s+"
        r"(project|app|application|code|repo|repository)\s*[\.\!]*\s*$"
    ),
    rx(r"^\s*(make|do)\s+(it|this)\s+(better|good|properly)\s*[\.\!]*\s*$"),
    rx(r"^\s*(fix|improve)\s+everything\s*[\.\!]*\s*$"),
    rx(r"^\s*make\s+the\s+(project|app|application|code)\s+better\s*[\.\!]*\s*$"),
]

BROAD_FIX_EVERYTHING = rx(
    r"\b(read|review|open|go through)\s+(the\s+)?(entire|whole|every)\s+"
    r"(repo|repository|codebase|file)\b.{0,80}\bfix\b.{0,30}\b(everything|"
    r"all|whatever)\b"
)

CONCRETE_DOMAIN_NOUN = rx(
    r"\b(login|auth|authentication|authorization|checkout|payment|"
    r"api|endpoint|database|db|test|bug|error|500|timeout|memory|"
    r"performance|security|validation|logging|ui|frontend|backend|"
    r"component|route|middleware|webhook|cache|caching|migration|"
    r"deployment|ci|build|dependency|token|password|reset|"
    r"rate.?limit|n\+1|query|leak|failure|failing)\b"
)

CONCRETE_OUTCOME_VERB = rx(
    r"\b(returns?|fails?|crashes?|throws?|stores?|uses?|"
    r"contains?|handles?|identify|locate|trace|add|remove|"
    r"produce|return|report|summarize|review|check|verify|confirm|"
    r"validate|inspect)\b"
)

PERSISTENT_RULE_TRIGGER = rx(r"\b(every time|always|must|never)\b")
PERSISTENT_RULE_DOMAIN = rx(
    r"\b(project|api|database|migration|production|configuration|"
    r"tests?|security|logging|convention|rule|pull request|pr)\b"
)

CONTEXT_HEAVY_WORDS = rx(
    r"\b(everything we'?ve discussed|entire conversation|whole conversation|"
    r"re.?read everything|all previous|from the beginning|for (hours|the "
    r"last \w+ hours)|long session)\b"
)

BREADTH_WORDS = rx(r"\b(entire|whole|everything|all|every)\b")
UNBOUNDED_WORDS = rx(
    r"\b(perfect|all possible|from every angle|whatever you think|"
    r"anything|everything you find)\b"
)

INDEPENDENT_INVESTIGATION_VERBS = rx(
    r"\b(investigate|trace|compare|analy[sz]e|diagnose|identify)\b"
)

# A concrete, narrow action that stays low-risk even without a formal
# constraints/done statement (spec section 27: don't over-penalize).
TRIVIAL_ACTION = rx(
    r"\b(typo|rename|bump (the )?version|one-line|minor fix|small fix|"
    r"quick fix|tweak|correct the spelling)\b"
)
