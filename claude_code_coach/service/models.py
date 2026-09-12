"""JSON serialization for the Phase 2 HTTP API.

Every function here only ever reshapes data that already came from a real
`analyzer`/`runtime`/`providers` call — nothing here invents a field. Enum
values are always serialized via `.value` (never Python's default
`repr`/`str`, which would leak `ClassName.MEMBER` into the JSON).
"""

from __future__ import annotations

API_VERSION = "v1"


def _enum_value(x) -> str:
    return x.value if hasattr(x, "value") else str(x)


def health_response() -> dict:
    return {"service": "claude-code-coach", "api_version": API_VERSION, "status": "ready"}


def status_response(*, connected: bool, runtime_configured: bool, runtime_state: str,
                     project_root: str | None, last_event_at: str | None) -> dict:
    return {
        "connected": connected,
        "runtime_configured": runtime_configured,
        "runtime_state": runtime_state,
        "project_root": project_root,
        "last_event_at": last_event_at,
    }


def session_summary_dict(summary) -> dict:
    return {
        "session_id": summary.session_id,
        "title": summary.title,
        "started_at": summary.started_at,
        "last_event_at": summary.last_event_at,
        "prompts": summary.prompts,
        "tool_calls": summary.tool_calls,
        "searches": summary.searches,
        "reads": summary.reads,
        "edits": summary.edits,
        "commands": summary.commands,
        "skills_or_agents": summary.skills_or_agents,
        "compactions": summary.compactions,
        "ended": summary.ended,
    }


def signal_dict(signal) -> dict:
    return {
        "kind": signal.kind,
        "level": signal.level,
        "message": signal.message,
        "what_happened": signal.what_happened,
        "why_it_matters": signal.why_it_matters,
        "try_instead": signal.try_instead,
        "evidence": signal.evidence,
    }


def session_response(runtime_status, *, cwd: str | None) -> dict:
    # Phase 4E (docs/SHARED_COACH_STATE.md §3/4/5): both new fields are
    # additive/backward-compatible — an older client simply never reads
    # them. `primary_signal` reuses signal_dict on the exact same
    # RuntimeSignal objects already in `signals`; no second selection
    # system, no field the existing V5 model can't already support.
    from ..runtime.signal_priority import pick_primary_signal

    primary = pick_primary_signal(runtime_status.signals)
    return {
        "cwd": cwd,
        "connection_state": _enum_value(runtime_status.state),
        "session": (
            session_summary_dict(runtime_status.current_session)
            if runtime_status.current_session else None
        ),
        "context_health": runtime_status.context_health,
        "signals": [signal_dict(s) for s in runtime_status.signals],
        "primary_signal": signal_dict(primary) if primary else None,
        "coaching_paused": runtime_status.paused,
    }


def dimension_dict(analysis) -> dict:
    return {name: {"status": d.status, "detail": d.detail} for name, d in analysis.dimensions.items()}


def opportunity_dict(opp) -> dict:
    return opp.to_dict()


def analysis_response(analysis) -> dict:
    """Phase 3: /api/v1/analyze — the exact same AnalysisResult the desktop
    Prompt Inspector already renders, reshaped as JSON. No score/rating/
    dimension logic lives here; analyzer.analyze_prompt computed all of it.
    """
    return {
        "prompt": analysis.prompt,
        "task_type": analysis.task_type,
        "score": analysis.score,
        "rating": analysis.rating,
        "dimensions": dimension_dict(analysis),
        "good": analysis.good,
        "warnings": analysis.warnings,
        "opportunities": [opportunity_dict(o) for o in analysis.opportunities],
        "breadth_level": analysis.breadth_level,
        "vague_goal": analysis.vague_goal,
        "context_note": analysis.context_note,
    }


def suggestion_response(suggestion) -> dict:
    """Phase 3: /api/v1/suggest — analyzer.prompt_rewriter.suggest_prompt's
    PromptSuggestion, unchanged. suggested_text is None when the
    deterministic rewriter has no safe rewrite to offer — the caller must
    render that as "no safe rewrite available", never fabricate one.
    """
    return {
        "category": _enum_value(suggestion.category),
        "message": suggestion.message,
        "suggested_text": suggestion.suggested_text,
    }


def approach_recommendation_dict(rec) -> dict:
    return {
        "kind": rec.kind,
        "level": rec.level,
        "icon": rec.icon,
        "message": rec.message,
        "what_happened": rec.what_happened,
        "why_it_matters": rec.why_it_matters,
        "try_instead": rec.try_instead,
        "evidence": rec.evidence,
    }


def approach_response(report) -> dict:
    """Phase 3: /api/v1/approach — integration.approach_advisor's
    ApproachReport. `recommendations` preserves every recommendation
    integration.recommend_approach produced, already ordered by real
    confidence/level (see ApproachReport.top()) — the caller picks how
    many to show, but must never re-order by inventing its own scoring."""
    ranked = report.top(len(report.recommendations)) if report.recommendations else []
    return {
        "recommendations": [approach_recommendation_dict(r) for r in ranked],
    }


def environment_response(snapshot) -> dict:
    return {
        "project_root": snapshot.project_root,
        "scanned_at": snapshot.scanned_at,
        "counts": snapshot.counts,
        "claude_md": [
            {"path": d.path, "scope": _enum_value(d.scope), "size_bytes": d.size_bytes,
             "modified": d.modified, "preview": d.preview}
            for d in snapshot.claude_md
        ],
        "skills": [
            {"name": s.name, "path": s.path, "description": s.description,
             "source": _enum_value(s.source), "modified": s.modified}
            for s in snapshot.skills
        ],
        "agents": [
            {"name": a.name, "path": a.path, "description": a.description,
             "source": _enum_value(a.source), "modified": a.modified}
            for a in snapshot.agents
        ],
        "mcp_servers": [
            {"name": m.name, "server_type": m.server_type, "source": _enum_value(m.source),
             "enabled": m.enabled}
            for m in snapshot.mcp_servers
        ],
        "errors": snapshot.errors,
    }
