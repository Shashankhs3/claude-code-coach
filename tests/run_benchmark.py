"""Runs the benchmark dataset against the analyzer and reports accuracy.

This is a diagnostic tool (spec section 26), not a strict pass/fail gate —
it prints expected vs. actual classification/rating/opportunities so the
heuristics can keep being tuned. Run with:

    python tests/run_benchmark.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.analyzer import analyze_prompt

BENCHMARK_PATH = Path(__file__).parent / "benchmark_prompts.json"


def run() -> dict:
    cases = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))

    total = len(cases)
    rating_pass = 0
    task_type_pass = 0
    task_type_checked = 0
    opp_pass = 0
    failures = []

    for case in cases:
        result = analyze_prompt(case["prompt"])
        actual_kinds = {o.kind for o in result.opportunities}
        expected_kinds = set(case.get("expected_opportunities", []))

        rating_ok = result.rating in case["expected_ratings"]
        task_type_ok = True
        if case.get("expected_task_type"):
            task_type_checked += 1
            task_type_ok = result.task_type == case["expected_task_type"]
            if task_type_ok:
                task_type_pass += 1

        opp_ok = expected_kinds.issubset(actual_kinds)
        if opp_ok:
            opp_pass += 1

        if rating_ok:
            rating_pass += 1

        if not (rating_ok and task_type_ok and opp_ok):
            failures.append({
                "id": case["id"],
                "category": case["category"],
                "prompt": case["prompt"][:80],
                "expected_ratings": case["expected_ratings"],
                "actual_rating": result.rating,
                "actual_score": result.score,
                "expected_task_type": case.get("expected_task_type"),
                "actual_task_type": result.task_type,
                "expected_opportunities": sorted(expected_kinds),
                "actual_opportunities": sorted(actual_kinds),
            })

    print(f"Benchmark cases:        {total}")
    print(f"Rating band matches:    {rating_pass}/{total} ({100 * rating_pass // total}%)")
    if task_type_checked:
        print(f"Task-type matches:      {task_type_pass}/{task_type_checked} "
              f"({100 * task_type_pass // task_type_checked}%)")
    print(f"Opportunity matches:    {opp_pass}/{total} ({100 * opp_pass // total}%)")
    print()

    if failures:
        print(f"--- {len(failures)} case(s) diverged from expectations ---")
        for f in failures:
            print(
                f"[#{f['id']:>2} {f['category']}] \"{f['prompt']}\"\n"
                f"    rating: expected {f['expected_ratings']} got {f['actual_rating']} "
                f"(score {f['actual_score']})\n"
                f"    task_type: expected {f['expected_task_type']!r} got {f['actual_task_type']!r}\n"
                f"    opportunities: expected {f['expected_opportunities']} got {f['actual_opportunities']}"
            )
    else:
        print("All benchmark cases matched expectations.")

    return {
        "total": total,
        "rating_pass": rating_pass,
        "task_type_pass": task_type_pass,
        "task_type_checked": task_type_checked,
        "opp_pass": opp_pass,
        "failures": failures,
    }


if __name__ == "__main__":
    run()
