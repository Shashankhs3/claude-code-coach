"""Cross-prompt pattern detection: repeated workflows over history.

Spec sections 10-14: Skill/Agent/CLAUDE.md candidates must be based on
*repeated* patterns across history, not a single keyword in one prompt.
This module clusters similar historical prompts with plain-stdlib text
similarity (no ML/embeddings dependency) and turns qualifying clusters into
named, confidence-rated candidates.
"""

from __future__ import annotations

import re
from collections import Counter

_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is",
    "are", "be", "this", "that", "it", "with", "as", "at", "by", "from",
    "your", "you", "i", "then", "please", "do", "does", "did",
}


def tokenize(text: str) -> set:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_./-]{2,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def cluster_rows(rows: list[dict], threshold: float = 0.4) -> list[list[dict]]:
    """Greedy similarity clustering over prompt text. O(n^2), fine for local history."""
    token_sets = [(tokenize(r["prompt"]), r) for r in rows]
    used = [False] * len(token_sets)
    clusters: list[list[dict]] = []

    for i in range(len(token_sets)):
        if used[i]:
            continue
        tokens_i, row_i = token_sets[i]
        cluster = [row_i]
        used[i] = True
        for j in range(i + 1, len(token_sets)):
            if used[j]:
                continue
            tokens_j, row_j = token_sets[j]
            if jaccard(tokens_i, tokens_j) >= threshold:
                cluster.append(row_j)
                used[j] = True
        clusters.append(cluster)

    return clusters


def _cluster_name(cluster: list[dict]) -> str:
    words: Counter = Counter()
    for row in cluster:
        words.update(tokenize(row["prompt"]))
    top = [w for w, _ in words.most_common(4)]
    if not top:
        return "Repeated workflow"
    return " ".join(w.capitalize() for w in top[:3])


def _confidence(occurrences: int, strong: bool) -> str:
    if occurrences >= 5 or (occurrences >= 3 and strong):
        return "high"
    if occurrences >= 3 or (occurrences >= 2 and strong):
        return "medium"
    return "low"


def _has_opportunity(row: dict, kind: str) -> bool:
    return any(o.get("kind") == kind for o in row.get("opportunities", []))


def skill_candidates(rows: list[dict]) -> list[dict]:
    """Repeated multi-step workflows that could become a Skill."""
    source = [
        r for r in rows
        if r.get("task_type") in ("review", "security_review", "repetitive_workflow")
        or _has_opportunity(r, "skill")
    ]
    if len(source) < 2:
        return []

    candidates = []
    for cluster in cluster_rows(source, threshold=0.35):
        if len(cluster) < 3:
            continue
        strong = any(_has_opportunity(r, "skill") for r in cluster)
        candidates.append({
            "name": _cluster_name(cluster) + " Workflow",
            "occurrences": len(cluster),
            "confidence": _confidence(len(cluster), strong),
            "reason": "Similar multi-step workflow detected repeatedly.",
            "examples": [r["prompt"][:140] for r in cluster[:3]],
        })

    candidates.sort(key=lambda c: c["occurrences"], reverse=True)
    return candidates


def agent_candidates(rows: list[dict]) -> list[dict]:
    """Independent-investigation tasks that could be delegated to an Agent."""
    source = [
        r for r in rows
        if r.get("task_type") in ("investigation", "debugging")
        and _has_opportunity(r, "agent")
    ]
    if not source:
        return []

    candidates = []
    for cluster in cluster_rows(source, threshold=0.3):
        best_conf = "low"
        for r in cluster:
            for o in r.get("opportunities", []):
                if o.get("kind") == "agent" and o.get("confidence") == "high":
                    best_conf = "high"
                elif o.get("kind") == "agent" and o.get("confidence") == "medium" and best_conf != "high":
                    best_conf = "medium"
        candidates.append({
            "name": _cluster_name(cluster) + " Investigation",
            "occurrences": len(cluster),
            "confidence": best_conf,
            "reason": "Task involves independent investigation across multiple components.",
            "examples": [r["prompt"][:140] for r in cluster[:3]],
        })

    candidates.sort(key=lambda c: c["occurrences"], reverse=True)
    return candidates


def claude_md_candidates(rows: list[dict]) -> list[dict]:
    """Persistent project rules that could live in CLAUDE.md."""
    source = [r for r in rows if _has_opportunity(r, "claude_md")]
    if not source:
        return []

    candidates = []
    for cluster in cluster_rows(source, threshold=0.3):
        candidates.append({
            "name": _cluster_name(cluster) + " Rule",
            "occurrences": len(cluster),
            "confidence": _confidence(len(cluster), strong=True) if len(cluster) > 1 else "medium",
            "reason": "Reads like a persistent project rule rather than a one-off task.",
            "examples": [r["prompt"][:140] for r in cluster[:3]],
        })

    candidates.sort(key=lambda c: c["occurrences"], reverse=True)
    return candidates


def context_stats(rows: list[dict]) -> dict:
    """Aggregate, session-agnostic context-health signals.

    These numbers describe prompt *habits* recorded locally — they are not,
    and must never be presented as, actual Claude token usage.
    """
    if not rows:
        return {
            "avg_prompt_words": 0,
            "avg_score": 0,
            "broad_task_pct": 0,
            "repeated_instruction_pct": 0,
            "context_warning_count": 0,
            "suggest_compaction": False,
            "total": 0,
        }

    total = len(rows)
    avg_words = round(sum(len(r["prompt"].split()) for r in rows) / total, 1)
    avg_score = round(sum(r["score"] for r in rows) / total)
    broad = sum(1 for r in rows if int(r.get("breadth_level") or 0) >= 1)
    context_warnings = sum(1 for r in rows if r.get("context_flag") == "noisy")

    clusters = cluster_rows(rows, threshold=0.4)
    repeated = sum(len(c) for c in clusters if len(c) >= 3)

    broad_pct = round(100 * broad / total)
    repeated_pct = round(100 * repeated / total)

    suggest_compaction = context_warnings >= 3 or repeated_pct >= 40

    return {
        "avg_prompt_words": avg_words,
        "avg_score": avg_score,
        "broad_task_pct": broad_pct,
        "repeated_instruction_pct": repeated_pct,
        "context_warning_count": context_warnings,
        "suggest_compaction": suggest_compaction,
        "total": total,
    }
