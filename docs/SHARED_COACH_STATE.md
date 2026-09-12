# Shared Coach State — Phase 4E Audit + Ownership Model

Phase 4A–4D-A built the standalone Coach service and made the Desktop app a
client of it (with an embedded fallback). This phase's job is narrower: make
sure Desktop and VS Code, when both pointed at the same standalone service,
**agree** — same session, same title, same primary signal, same pause state
— instead of each computing part of the picture on its own.

> **Standalone Service = canonical backend.**
> **Desktop = a client of it** (with a temporary embedded fallback when none exists).
> **VS Code = a client of it.**

This document is the audit called for by Step 1, plus the ownership model
Steps 2–20 describe. No code changes were made before this file existed.

## 1. Audit — what each piece of state actually is today

| State | Where it lives today | Backend-derived? | Persisted? | Recomputed independently by...? |
|---|---|---|---|---|
| Runtime events (`runtime_events` table) | `coach.db`, written by `hook_receiver.py` → drained by whichever process's `RuntimeCoach.poll_and_store()` currently owns draining | Yes | Yes (SQLite) | No — single shared table, single drain owner at a time (`CoachController.poll_runtime()`'s `has_reachable_backend()` guard; the standalone service's own `_drain_loop`) |
| `runtime_sessions` row (prompts/tool calls/edits/etc, session title) | `coach.db`, computed by `RuntimeCoach.status()` from `runtime_events` | Yes | Yes | **No, but reached two different ways:** VS Code always calls `RuntimeCoach.status()` *through* the standalone service's `/api/v1/session`. Desktop's `CoachController.runtime_status()` calls the **same Python function directly** (`self.runtime_coach.status(...)`), never through HTTP — safe today only because Desktop and the service share one `coach.db` file, so both calls are the same deterministic function over the same data. This is *not* a second interpretation of events, but it is a second call path, worth naming. |
| `RuntimeSignal` list (coaching signals) | Computed inside `RuntimeCoach.status()` via `runtime_analyzer.analyze_session()`/`repeated_instructions_signal()` | Yes | No (recomputed per call) | No — same function, same data, both processes. |
| **Primary/"current" coaching signal** | **VS Code only**: `coaching.ts`'s `pickPrimarySignal()` (sorts by `level`) — computed client-side after fetching the full `signals` list. **Desktop**: no concept of "the one primary signal" exists at all; `ui/runtime.py` just lists every signal as an unordered `SignalCard`. | **No** — this is the one piece of real signal-selection logic that lives only in the VS Code layer today. | No | **Yes — this is the gap Step 4 is about.** Only one client (VS Code) does this selection; Desktop does none. Not yet a disagreement (Desktop asserts no primary), but the selection logic is not centralized. |
| Session title | `runtime/session_title.py`, computed inside `RuntimeCoach.status()` (same call as the session row above) | Yes | No (derived per call, stable per session by construction) | No |
| Context health | `runtime_analyzer.session_coherence()`, computed inside `RuntimeCoach.status()` | Yes | No | No |
| Verification state | One `RuntimeSignal` (`verification_missing`/`verification_done`) in the same signals list | Yes | No | No |
| Connection state (`ConnectionState`) | `RuntimeCoach._connection_state()`: hooks-installed flag + last event time + event-source availability | Yes | Partial (`runtime_hooks_installed` setting) | No |
| **Pause state** | **VS Code only**: `coachingState.ts`, backed by `vscode.Memento` (`context.globalState`) — local to the VS Code installation, never touches the backend. **Desktop**: no "pause coaching" concept exists; the closest thing, the "Runtime Coach enabled" checkbox (`runtime_enabled`), is a *different* concept — it swaps the event source to `NullRuntimeEventSource`, i.e. it stops **collecting** events, not just interventions, and its effect is local-process-only for the connection-state label. | **No** | VS Code: yes (Memento). Desktop's `runtime_enabled`: yes (`coach.db` setting), but semantically wrong for "pause coaching" per Step 5's rule. | **Yes — this is the other gap Step 5 is about.** Two completely independent, non-communicating pause concepts exist, one of which (Desktop's) isn't even about pausing interventions. |
| Environment snapshot (Skills/Agents/CLAUDE.md) | `ClaudeCodeEnvironmentProvider.scan()`, cached in `coach.db` (`environment_scans` etc.) | Yes | Yes | No — same provider, same cache table |
| Backend availability / mode (`BackendMode`) | Desktop: `CoachController.current_backend_mode()` (embedded/standalone/unavailable), from `service/lifecycle.py` + `service/client.py`. VS Code: `coachClient.ts`'s `readDiscovery()` (reachable/unreachable + a specific diagnostic). | N/A — this *is* the discovery layer itself | `service.json` (transient, rewritten each service start) | Each client asks the same question ("is a compatible service.json valid and alive") via its own reader, but both readers implement the *same* three checks (shape, PID liveness, `api_version`) by explicit design (`service/client.py`'s docstring: "mirrors...conceptually, not implementation"). Not a source of disagreement — this duplication is intentional and pre-existing, not something this phase changes. |
| Backend version / `api_version` | `service.json`, written by `service/lifecycle.py` | Yes | Transient | No |
| Notification dedup (15-minute window) | VS Code only: `coachingState.ts`'s `wasRecentlyNotified`/`markNotified` (Memento) | No — deliberately client-local | Yes (Memento) | N/A — see §7 below; this is correctly client-local, not a gap |
| Project/session scoping (`cwd`/`project_root`) | Query params on `/api/v1/session`, `/api/v1/environment`, `/api/v1/status`; `runtime_sessions.cwd` column | Yes | Yes | No — both clients pass their own workspace path; the backend already scopes by it (`list_runtime_sessions(cwd=...)`) |
| Panel open/closed, selected tab, window layout, VS Code status bar text | Each client's own UI framework state | No | No (or client-local storage only) | Correctly client-local — not addressed by this phase |

### What this means concretely

Two real gaps exist, and they're exactly the two Steps 4 and 5 call out:

1. **Primary signal selection** exists only in `vscode-extension/src/coaching.ts`. Desktop doesn't select one at all (it shows the full list), so there's no active *disagreement* today, but there's also no shared answer a future Desktop "Current Coaching" view (or any other client) could reuse.
2. **Pause** is two unrelated, non-communicating things: a VS Code-only local toggle, and a Desktop-only "stop collecting events" toggle that was never meant to mean "pause coaching" in the first place.

Everything else backend-derived (session, title, signals, context health,
verification, connection state, environment) is **already** single-source-of-truth
in practice, because Desktop and the standalone service are two processes
reading/writing the one `coach.db` file, running the identical Python
functions. This phase does not need to introduce a new sync mechanism for
that data — it needs to (a) centralize primary-signal selection, (b) add a
real shared pause flag, and (c) make sure VS Code, which has no direct DB
access, can read/write both of those through the API.

## 2. Proposed ownership model

### Backend-owned (canonical in the standalone service / shared `coach.db`)

- Current relevant session (`session_id`, per `cwd`/`project_root`)
- Session title
- Runtime/connection state
- Full coaching signal list + **primary coaching signal** (newly centralized, §4)
- Context health
- Verification state (one of the signals above)
- Detected environment (Skills/Agents/CLAUDE.md)
- Backend availability / mode / version (via `service.json` discovery — unchanged)
- **Shared pause state** (newly added, §5) — a plain `coaching_paused` flag in `coach.db`, read by every process that computes `RuntimeStatus`, settable by either client through the API

### Client-local (never synchronized)

- Panel open/closed, selected tab, scroll position, collapse/expand state
- VS Code status bar text/icon (a *rendering* of shared state, not itself shared)
- Desktop window layout
- VS Code notification settings (`notificationsEnabled`, `notificationLevel`) — a per-install preference, deliberately not shared (§6)
- VS Code's 15-minute notification dedup memory — deliberately local (§7)
- Desktop's "Runtime Coach enabled" (event-collection) toggle — a different, pre-existing concept from pause; left as-is (§5)

## 3/4. Current coaching state + shared primary-signal selection

`session_response()` (`service/models.py`) already returns the full
`signals` list untouched. This phase adds one derived, read-only field
computed from that same list — no new fields invented beyond what
`RuntimeSignal` already carries:

```json
"primary_signal": {
  "kind": "verification_missing",
  "level": "medium",
  "message": "...",
  "what_happened": "...",
  "why_it_matters": "...",
  "try_instead": "...",
  "evidence": {}
}
```

(`null` when there are no signals.) Selection logic: a new
`runtime/signal_priority.py::pick_primary_signal()` — the same `level`
ordering (`high` > `medium` > `low`) `coaching.ts`'s `pickPrimarySignal()`
already uses, moved to be the one place both languages' clients can point
at. VS Code's `pickPrimarySignal()` (TypeScript) stays as a **fallback**
only, used if an older/incompatible service response omits `primary_signal`
(Step 21 compatibility) — it is not deleted, and its own tests are untouched.
Desktop's `ui/runtime.py` calls the same Python function directly (no HTTP
round trip needed, same reasoning as session/signals above) purely to order
its existing signal list so the same signal leads — it does not gain a new
"Current Coaching" widget (that would be the redesign the brief rules out).

## 5. Shared pause state

New, additive DB setting: `coaching_paused` (`"0"`/`"1"`, default `"0"`),
read by `RuntimeCoach.status()` and exposed as `RuntimeStatus.paused` /
`session_response()`'s `"coaching_paused"` field — the same call path every
other shared field already uses.

- **Desktop → Pause**: a new checkbox in Settings → Coach Service writes
  the DB setting directly (same pattern as `runtime_enabled`/
  `runtime_collect_content`) and nudges the existing `vscode_signal.txt`
  file so a co-located standalone service's VS Code windows refresh
  promptly, without waiting for their next poll tick.
- **VS Code → Pause/Resume**: the existing `claudeCodeCoach.pauseCoaching`/
  `resumeCoaching` commands now call a new `POST /api/v1/pause` endpoint
  instead of writing to `vscode.Memento`. If the service is unreachable,
  the command reports that plainly (mirrors the existing "Coach is offline"
  messaging elsewhere) rather than pretending to pause something with no
  effect.
- `CoachingStateStore.isPaused()/setPaused()` (Memento) are **left in
  place, untouched, still tested** — they simply stop being the source
  `extension.ts` reads for the live pause state. (Removing them would be
  pure churn for no behavioral benefit and would needlessly touch a green
  test file.)
- Pause **never** touches `runtime_enabled`/hook event collection or the
  service process itself — `RuntimeCoach.poll_and_store()` and the
  service's `_drain_loop` are completely unaffected by `coaching_paused`.
  Signals keep being computed and returned while paused; only the
  *interruption* (status bar Attention, native notification, and — new —
  Desktop's own "leading" signal framing) is suppressed. This mirrors the
  panel's existing "Coaching paused" card, which already lists the
  observed signals underneath.
- Pause is **global**, not per-project — matching VS Code's pre-existing
  documented scope choice for the same feature. Introducing per-project
  pause now would be new product behavior this phase doesn't call for.

### Embedded fallback edge case (Step 19)

While Desktop is `EMBEDDED_FALLBACK` (no standalone service reachable),
`coaching_paused` still lives in Desktop's own `coach.db` — pausing affects
only that Desktop/backend instance, because nothing else is reading that
database file yet. VS Code, finding no valid `service.json`, stays
`Offline` and never reads or writes this flag. Once a real standalone
service appears (and Desktop hands off to it, per the existing Phase 4D-A
handoff check), both processes are reading/writing the *same* `coach.db`,
and pause becomes shared automatically — no new cross-process protocol
needed, by construction.

## 6/7. Notification settings and deduplication — unchanged

`notificationsEnabled`/`notificationLevel` (VS Code settings) and the
15-minute `(workspace, session, kind)` dedup window in `coachingState.ts`
are left exactly as they are. Per Step 6/7: **signal existence** must be
shared (already true — both clients see the same `signals` list from the
same backend call), but **notification delivery** may legitimately differ
per client/install, and no concrete synchronization problem exists here —
Desktop has no native-notification feature to begin with, so there is
nothing to duplicate against. Not touched.

## 8/9/10. Session state, project isolation, multiple windows

Already correct, pre-existing behavior, unchanged by this phase:
`RuntimeCoach.status(cwd=...)` / `list_runtime_sessions(cwd=...)` scope to
the most recent session for that `cwd`; every read endpoint
(`/status`, `/session`, `/environment`) takes an explicit `project_root`/
`cwd`, so two VS Code windows (or Desktop + VS Code) open on different
projects each supply their own identity and get their own session — never
a single "current project" global. This phase adds no new global except
the intentionally-global `coaching_paused` flag (§5).

## 11/12/13. Live updates

- **VS Code**: unchanged mechanism (`vscode_signal.txt` watched by
  `FileSignalWatcher`, plus the existing 5s poll fallback). The only change
  is that pause changes now also touch this file (§5), and `extension.ts`'s
  own poll tick reads `coaching_paused` from `/api/v1/session` instead of
  a local Memento flag — so the status bar and the panel, which both
  ultimately read the same `/api/v1/session` response per tick, can no
  longer disagree (closing the exact "notification = warning, status bar =
  Ready" class of bug named in Step 13).
- **Desktop**: unchanged — `ui/runtime.py`'s existing 3-second `QTimer`
  poll already re-reads `RuntimeCoach.status()` (now including `paused`
  and a priority-ordered signal list) on every tick. No new timer.

## 14. API

- `GET /api/v1/session` — **extended** (backward compatible, additive):
  `"coaching_paused": bool`, `"primary_signal": RuntimeSignal | null`.
- `POST /api/v1/pause` — **new**, minimal, non-destructive: body
  `{"paused": bool}`, returns `{"coaching_paused": bool}`. Chosen over
  extending a GET response because this is the one piece of *shared,
  mutable* state VS Code needs to change remotely (it has no DB access);
  every other synchronized value here stays read-only through the API, per
  the "avoid unnecessary endpoints" / "no destructive operations" rules.
- `API_VERSION` stays `"v1"` — both changes are additive, matching the
  existing documented policy in `service/lifecycle.py` ("adding a field...
  does not require a bump").

## 17/18. Backend mode / embedded fallback boundary

Unchanged and reconfirmed by this audit: VS Code's `coachClient.ts` only
ever reads `service.json` in the shared app-data directory — it cannot
and does not distinguish "Desktop's embedded copy" from "a standalone
process," by design (both write the identical discovery contract). This
phase does not add any VS Code-side concept of "the Desktop app" — it
remains a pure client of whatever process currently owns `service.json`.

## 21. Compatibility

`DimensionResult`'s `status` values and `providers.models.Provenance`'s
`DETECTED`/`POSSIBLE`/`INFERRED`/`UNKNOWN` states are untouched by this
phase — nothing here changes environment-discovery or prompt-analysis
contracts. New JSON fields are additive/optional so an older VS Code
build talking to a newer service (or vice versa) degrades gracefully:
missing `primary_signal` → VS Code's local `pickPrimarySignal` fallback;
missing `coaching_paused` → treated as `false` (not paused), matching the
pre-existing default.
