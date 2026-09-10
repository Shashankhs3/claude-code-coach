"""Extracts structured, user-provided information out of a prompt.

Purely regex/heuristic (no AI API, per spec) — this only ever *lifts out*
wording the user already typed. It never invents technical facts; anything
not present in the prompt is simply absent from the extraction, and the
rewriter (prompt_rewriter.py) falls back to neutral phrasing for those gaps
rather than guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import lexicon as lex

_FILE_TOKEN = re.compile(
    r"`([^`]+\.\w{1,5})`|"
    r"\b([\w./-]+\.(?:py|js|jsx|ts|tsx|java|go|rs|cs|cpp|c|rb|php|sql|md|json|yaml|yml))\b"
)
_FUNCTION_TOKEN = re.compile(r"`?\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(\)`?")
_ERROR_WORDS = re.compile(
    r"\b(cannot|can't|fails?|failing|failure|error|exception|crash(es|ed)?|"
    r"returns?\s+(a\s+)?(\d{3}|error)|instead of|no longer|broken|timeout|"
    r"after the latest|since the (latest|last))\b", re.I
)
_EXPECTED_WORDS = re.compile(
    r"\b(should|expected to|supposed to|is meant to|needs? to)\b", re.I
)

_CLAUSE_SPLIT = re.compile(r"(?<=[.!?;\n])\s+")

# "across A, B and C" / "in A, B, and C" style enumerations used to detect
# independent workstreams (Feature 7 / spec section on parallel work).
_ENUMERATION = re.compile(
    r"\b(?:across|in|for|spanning)\s+([a-z][\w /-]*(?:,\s*[a-z][\w /-]*)*"
    r"(?:,?\s+and\s+[a-z][\w /-]*))",
    re.I,
)
_SEQUENTIAL_CONNECTOR = re.compile(
    r"\b(then|after that|once (that|this|it)('s| is) done|afterwards?|"
    r"next,|following that)\b", re.I
)


@dataclass
class PromptExtraction:
    files: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    expected_behavior: list[str] = field(default_factory=list)
    error_descriptions: list[str] = field(default_factory=list)
    requested_outputs: list[str] = field(default_factory=list)
    domain_areas: list[str] = field(default_factory=list)
    independent_areas: list[str] = field(default_factory=list)
    has_sequential_connector: bool = False


def _clauses(prompt: str) -> list[str]:
    return [c.strip() for c in _CLAUSE_SPLIT.split(prompt.strip()) if c.strip()]


_GENERIC_TRAILING_NOUNS = re.compile(
    r"\s+(areas?|components?|parts?|modules?|sections?|layers?)$", re.I
)


def _strip_generic_suffix(text: str) -> str:
    return _GENERIC_TRAILING_NOUNS.sub("", text).strip()


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def extract(prompt: str) -> PromptExtraction:
    files = [m.group(1) or m.group(2) for m in _FILE_TOKEN.finditer(prompt)]
    functions = [m.group(1) + "()" for m in _FUNCTION_TOKEN.finditer(prompt)]

    clauses = _clauses(prompt)
    constraints = [c for c in clauses if lex.CONSTRAINT_WORDS.search(c)]
    error_descriptions = [c for c in clauses if _ERROR_WORDS.search(c)]
    expected_behavior = [c for c in clauses if _EXPECTED_WORDS.search(c)]
    requested_outputs = [c for c in clauses if lex.OUTPUT_WORDS.search(c)]

    domain_areas = _dedupe(lex.CONCRETE_DOMAIN_NOUN.findall(prompt.lower()))

    independent_areas: list[str] = []
    for m in _ENUMERATION.finditer(prompt):
        parts = re.split(r",\s*|\s+and\s+", m.group(1))
        parts = [_strip_generic_suffix(p.strip()) for p in parts if p.strip() and len(p.strip()) > 1]
        parts = [p for p in parts if p]
        if len(parts) >= 2:
            independent_areas.extend(parts)
    independent_areas = _dedupe(independent_areas)

    return PromptExtraction(
        files=_dedupe(files),
        functions=_dedupe(functions),
        constraints=_dedupe(constraints),
        expected_behavior=_dedupe(expected_behavior),
        error_descriptions=_dedupe(error_descriptions),
        requested_outputs=_dedupe(requested_outputs),
        domain_areas=domain_areas,
        independent_areas=independent_areas,
        has_sequential_connector=bool(_SEQUENTIAL_CONNECTOR.search(prompt)),
    )
