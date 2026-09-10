"""Runs the runtime-coaching benchmark against fixture event sequences.

No live Claude Code installation is involved — every sequence is a raw hook
payload list fed through the real `event_parser.parse_hook_payload()`, the
exact same code path the real hook_receiver.py uses. Run with:

    python tests/run_runtime_benchmark.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.providers.models import ClaudeMdInfo, SkillInfo, Source
from claude_code_coach.runtime import event_parser, runtime_analyzer
from claude_code_coach.runtime.models import RuntimeEventType

BENCHMARK_PATH = Path(__file__).parent / "runtime_benchmark.json"

SEARCH = runtime_analyzer.SEARCH_TOOLS
READ = runtime_analyzer.READ_TOOLS
EDIT = runtime_analyzer.EDIT_TOOLS
EXEC = runtime_analyzer.EXEC_TOOLS


def _expand_case_8(case: dict) -> dict:
    """Case 8 wants 140 unsearched reads — generated here to keep the JSON readable."""
    if case["id"] != 8:
        return case
    events = list(case["sessions"][0]["raw_events"])
    for i in range(140):
        events.append({"hook_event_name": "PreToolUse", "tool_name": "Read",
                        "tool_input": {"file_path": f"src/generated/f{i}.py"}})
    case["sessions"][0]["raw_events"] = events
    case["expected_present"] = ["broad_exploration"]
    return case


def _build_summary(events) -> dict:
    summary = {"prompts": 0, "tool_calls": 0, "searches": 0, "reads": 0,
               "edits": 0, "commands": 0, "skills_or_agents": 0, "compactions": 0}
    for e in events:
        if e.event_type == RuntimeEventType.USER_PROMPT_SUBMIT:
            summary["prompts"] += 1
        elif e.event_type == RuntimeEventType.PRE_TOOL_USE:
            summary["tool_calls"] += 1
            if e.tool_name in SEARCH:
                summary["searches"] += 1
            elif e.tool_name in READ:
                summary["reads"] += 1
            elif e.tool_name in EDIT:
                summary["edits"] += 1
            elif e.tool_name in EXEC:
                summary["commands"] += 1
        elif e.event_type == RuntimeEventType.SUBAGENT_STOP:
            summary["skills_or_agents"] += 1
        elif e.event_type == RuntimeEventType.PRE_COMPACT:
            summary["compactions"] += 1
    return summary


def run() -> dict:
    cases = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
    cases = [_expand_case_8(c) for c in cases]

    total = len(cases)
    passed = 0
    failures = []

    for case in cases:
        env = case.get("environment", {})
        detected_skills = [
            SkillInfo(name=s["name"], path="/fake", description=s["description"],
                      source=Source.PROJECT, modified="")
            for s in env.get("skills", [])
        ]
        claude_mds = [
            ClaudeMdInfo(path=c["path"], scope=Source.PROJECT, size_bytes=0,
                         modified="", preview=c["preview"])
            for c in env.get("claude_md", [])
        ]

        all_signals = []
        all_prompt_events = []
        for sess in case["sessions"]:
            events = [
                event_parser.parse_hook_payload({**raw, "session_id": sess["session_id"]})
                for raw in sess["raw_events"]
            ]
            summary = _build_summary(events)
            ctx = None
            for e in reversed(events):
                if e.event_type == RuntimeEventType.USER_PROMPT_SUBMIT:
                    ctx = e.metadata
                    break
            signals = runtime_analyzer.analyze_session(
                events, summary, latest_prompt_context=ctx, claude_mds=claude_mds,
            )
            all_signals.extend(signals)
            all_prompt_events.extend(
                e for e in events if e.event_type == RuntimeEventType.USER_PROMPT_SUBMIT
            )

        all_signals.extend(runtime_analyzer.repeated_instructions_signal(
            all_prompt_events, detected_skills=detected_skills,
        ))

        kinds = {s.kind for s in all_signals}
        expected_present = set(case.get("expected_present", []))
        expected_absent = set(case.get("expected_absent", []))

        missing = expected_present - kinds
        unwanted = expected_absent & kinds
        ok = not missing and not unwanted

        if ok:
            passed += 1
        else:
            failures.append({
                "id": case["id"], "category": case["category"],
                "note": case.get("note", ""),
                "missing_signals": sorted(missing), "unwanted_signals": sorted(unwanted),
                "actual_signals": sorted(kinds),
            })

    print(f"Runtime benchmark cases: {total}")
    print(f"Passed:                  {passed}/{total} ({100 * passed // total}%)")
    print()

    if failures:
        print(f"--- {len(failures)} case(s) diverged from expectations ---")
        for f in failures:
            print(f"[#{f['id']:>2} {f['category']}] {f['note']}")
            if f["missing_signals"]:
                print(f"    MISSING (expected but absent): {f['missing_signals']}")
            if f["unwanted_signals"]:
                print(f"    UNWANTED (present but shouldn't be): {f['unwanted_signals']}")
            print(f"    actual signals: {f['actual_signals']}")
    else:
        print("All runtime benchmark cases matched expectations.")

    return {"total": total, "passed": passed, "failures": failures}


if __name__ == "__main__":
    run()
