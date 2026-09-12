"""The single deterministic "what should I lead with" signal selector.

Phase 4E (docs/SHARED_COACH_STATE.md §3/4): this used to exist only in
vscode-extension/src/coaching.ts's `pickPrimarySignal()`. Moved here so the
standalone service can expose one authoritative answer (`session_response()`'s
`primary_signal` field) that every client renders instead of re-deriving —
Desktop calls this function directly (same process, same data, no HTTP
needed, exactly like session/signal computation already works), VS Code
reads the backend's answer over the API and keeps its own TypeScript copy
only as a fallback for an older/incompatible service response (Step 21).

No new scoring system: this only sorts by `RuntimeSignal.level` (high >
medium > low), exactly as coaching.ts's version already did.
"""

from __future__ import annotations

from .models import RuntimeSignal

_LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2}


def pick_primary_signal(signals: list[RuntimeSignal]) -> RuntimeSignal | None:
    if not signals:
        return None
    return sorted(signals, key=lambda s: _LEVEL_ORDER.get(s.level, 9))[0]
