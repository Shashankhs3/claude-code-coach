"""Per-dimension habit trends and "today" summary statistics."""

from __future__ import annotations

from datetime import datetime

_DIMENSIONS = (
    ("goal_status", "Goal clarity"),
    ("scope_status", "Scope discipline"),
    ("investigation_status", "Search-first usage"),
    ("constraints_status", "Constraint usage"),
    ("done_status", "Definition of done"),
    ("output_status", "Output control"),
)


def habit_trends(rows: list[dict]) -> list[dict]:
    """Return, for each dimension, the % of *applicable* prompts that were clear."""
    trends = []
    for column, label in _DIMENSIONS:
        applicable = [r for r in rows if r.get(column) and r[column] != "na"]
        clear = [r for r in applicable if r[column] == "clear"]
        pct = round(100 * len(clear) / len(applicable)) if applicable else None
        trends.append({
            "label": label,
            "pct": pct,
            "sample_size": len(applicable),
        })
    return trends


def _opportunity_counts(rows: list[dict]) -> dict:
    counts = {"skill": 0, "agent": 0, "claude_md": 0, "context": 0, "search_first": 0}
    for row in rows:
        kinds_seen = set()
        for o in row.get("opportunities", []):
            kinds_seen.add(o.get("kind"))
        for kind in kinds_seen:
            if kind in counts:
                counts[kind] += 1
    return counts


def today_stats(rows: list[dict]) -> dict:
    today = datetime.now().date().isoformat()
    todays = [r for r in rows if str(r.get("timestamp", "")).startswith(today)]

    count = len(todays)
    avg = round(sum(r["score"] for r in todays) / count) if count else 0
    good = sum(len(r.get("good", [])) for r in todays)
    warnings = sum(len(r.get("warnings", [])) for r in todays)
    opp_counts = _opportunity_counts(todays)

    return {
        "count": count,
        "avg_score": avg,
        "good_count": good,
        "warning_count": warnings,
        "opportunities": opp_counts,
    }


def all_time_opportunity_counts(rows: list[dict]) -> dict:
    return _opportunity_counts(rows)
