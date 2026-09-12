# VS Code Integration (Phase 2, Phase 3, Phase 3B, Phase 4B, Phase 4C)

Developer reference for the local HTTP bridge between the Claude Code
Coach desktop app and the `vscode-extension/` companion extension. For the
design rationale and alternatives considered, see
[VSCODE_INTEGRATION_ARCHITECTURE.md](VSCODE_INTEGRATION_ARCHITECTURE.md)
(Phase 1). This document covers what was actually built.

**Phase 4C update**: "Desktop app" below now means *whichever process
started the Coach service* — the desktop app's embedded copy, or a
standalone `python -m claude_code_coach.service` process (Phase 4A). VS
Code has never cared which one it is (Phase 4B confirmed this); as of
Phase 4C, the desktop app itself doesn't fully either — see
[DESKTOP_SERVICE_MIGRATION.md](DESKTOP_SERVICE_MIGRATION.md). Exactly one
process owns the background drain loop at a time regardless of how many
Coach-aware processes are running.

## Architecture

```
Claude Code CLI
      │  hooks (unchanged, V4)
      ▼
hook_receiver.py  →  runtime_events/*.jsonl
      │
      ▼
Coach service (claude_code_coach/service/) — desktop-embedded (app.py)
OR standalone (python -m claude_code_coach.service, Phase 4A) — exactly
one of these is running at a time; app.py checks before starting its own
(Phase 4C)
      │
      ├── background drain loop (lifecycle.py) — persists new
      │   hook events into coach.db every 2s, independent of
      │   whether any desktop UI page is open
      │
      └── HTTP server (server.py) — 127.0.0.1 only, token-authed
              │
      ┌───────┴───────┐
      ▼               ▼
vscode-extension/   Desktop app (a pure HTTP client when it detected
(unchanged)         an already-running service instead of starting
                     its own — service/client.py, Phase 4C)
```

The service is a thin, Qt-free façade (`coach_service.py`) over the
**same** `analyzer`/`runtime`/`providers` functions the desktop UI already
calls — no analysis logic is duplicated.

## Files

```
claude_code_coach/service/
    __init__.py       exports start_service/stop_service/is_running/current_port
    models.py         JSON response shapes (health/status/session/environment)
    coach_service.py  the façade: health(), status(), session(), environment()
    server.py         CoachHTTPServer/CoachRequestHandler (http.server, stdlib)
    lifecycle.py       start/stop, service.json + signal-file writers, drain loop

vscode-extension/
    package.json, tsconfig.json
    src/coachClient.ts    HTTP client + service.json discovery
    src/fileSignal.ts     watches vscode_signal.txt
    src/statusBar.ts      Connecting/Ready/Offline/Paused
    src/coachPanel.ts     the "Open Coach" webview panel
    src/windowRegistry.ts per-window PID registry (forward-looking, unused so far)
    src/extension.ts      wires the above together
    src/test/             mocha + @vscode/test-electron test suite
```

## How the service starts

`app.py` calls `start_service()` right after `init_db()`, before
`window.show()`. It:

1. Generates a random token (`secrets.token_urlsafe(24)`).
2. Binds `CoachHTTPServer(("127.0.0.1", port), ...)` — **never** `0.0.0.0`.
3. Starts two plain `threading.Thread`s (not `QThread`s — neither touches a
   `QObject`, so there's no Qt thread-affinity concern):
   - `coach-http`: `httpd.serve_forever()`.
   - `coach-drain`: polls `runtime_events/*.jsonl` every 2 seconds and
     writes a line to `vscode_signal.txt` whenever new events land.
4. Writes `%USERPROFILE%\.claude_code_coach\service.json`.

A bind failure (e.g. the port is already in use) is caught, logged, and
`start_service()` returns `False` — **the desktop app starts normally
either way.** VS Code integration is simply unavailable for that run.

`app.aboutToQuit` calls `stop_service()`, which shuts down both threads
and removes `service.json`. A forceful kill (Task Manager, `taskkill /F`)
skips this cleanup, same as any other `aboutToQuit` handler — `service.json`
is left behind until the next graceful start/stop cycle overwrites or
removes it.

## Discovery file

`%USERPROFILE%\.claude_code_coach\service.json`:

```json
{
  "port": 47823,
  "token": "<random>",
  "pid": 12345,
  "started_at": "2026-09-11T00:59:08",
  "api_version": "v1"
}
```

Written atomically is not required here (it's a small single write, not a
read-modify-write), but it is fully rewritten on every start and removed
on clean shutdown — the extension always re-reads it rather than caching a
port, so a desktop restart with a new port/token is picked up on the
extension's very next request.

Default port is `47823` (`lifecycle.DEFAULT_PORT`); `start_service(port=0)`
binds an ephemeral port instead — used by the test suite so tests never
collide with a real running instance.

## API

All routes are `GET`, JSON in/out, under `http://127.0.0.1:<port>/api/v1/`.
Every request must carry a matching `X-Coach-Token` header.

| Endpoint | Query params | Returns |
|---|---|---|
| `/health` | — | `{service, api_version, status}` |
| `/status` | `project_root` (optional) | `{connected, runtime_configured, runtime_state, project_root, last_event_at}` |
| `/session` | `cwd` or `project_root` (optional) | `{cwd, connection_state, session, context_health, signals}` |
| `/environment` | `project_root` (optional) | Full `EnvironmentSnapshot` JSON (CLAUDE.md/Skills/Agents/MCP) |

`POST` to any route returns `405`. An unknown path returns `404`. A missing
or wrong token returns `401`. All error bodies are `{"error": "..."}` —
never a Python stack trace.

**Not exposed over HTTP, by design** (see Security below): installing/
removing hooks, saving a Skill/Agent, clearing data, `/analyze`,
`/suggest`, `/approach`. These remain desktop-only, confirmation-gated
actions — out of scope for Phase 2's read-only bridge.

## Authentication

A random token is generated at every service startup and required as the
`X-Coach-Token` header on every request. It is written to `service.json`
(same OS-account-level file permissions `coach.db` already has) and never
logged. This is defense-in-depth against another local process/user
probing the port on a shared machine — not a defense against a co-resident
process running as the *same* Windows account, which could read
`service.json` directly anyway. That limit is inherent to any
unauthenticated-by-OS-user loopback service and is documented here rather
than hidden.

## Workspace / session identity

`runtime_sessions` gained an additive `cwd` column (schema v5→v6,
`database/migrations.py`), populated from each session's `SessionStart`
hook metadata. `list_runtime_sessions(cwd=...)` and `RuntimeCoach.status(cwd=...)`
both accept an optional `cwd` filter, defaulting to the prior
global-most-recent behavior when omitted — every existing desktop-UI
caller is unaffected.

The extension sends `vscode.workspace.workspaceFolders[0].uri.fsPath` as
`cwd`/`project_root` on every request. Multi-root workspaces use the first
folder only in Phase 2 (documented limitation, not built around further).

A `cwd` with no matching session simply returns `session: null` — never a
guess, never another workspace's session.

## Signal mechanism

`vscode_signal.txt` (one line: `"<reason> <timestamp> <count>"`) is
rewritten by the background drain thread whenever it persists new hook
events. `fileSignal.ts` watches it via
`vscode.workspace.createFileSystemWatcher` and triggers an immediate
re-fetch instead of waiting for the fallback poll — turning "poll every
~5s" into "near-instant on real activity, poll as a fallback." The
extension also polls on a plain interval (`claudeCodeCoach.pollIntervalSeconds`,
default 5s) so a missed watcher event (e.g. the file didn't exist yet at
activation) is never a permanent stale state.

## Service lifecycle from the extension's side

| Scenario | Behavior |
|---|---|
| VS Code starts before the desktop app | `readDiscovery()` returns `null` → status bar shows Offline until the desktop app starts. |
| Desktop app starts after VS Code | Next poll/signal tick finds `service.json` → Ready. |
| Desktop app closes gracefully | `service.json` removed → next request fails cleanly → Offline. |
| Desktop app restarts | New `service.json` (new PID, possibly new port/token) → picked up on the extension's very next call, no extension reload needed. |
| VS Code window reloads | `deactivate()`/`activate()` re-run; no special handling needed. |

## Privacy

- No cloud API, no telemetry, no external network calls of any kind — the
  extension only ever talks to `127.0.0.1`.
- `/environment` responses have already passed through `providers/redaction.py`
  before ever reaching SQLite; the HTTP layer adds no new exposure.
- Prompt text is never sent to or requested by any Phase 2 endpoint.
- Logging (`server.py`'s `log_message`) records method/path/status only —
  never headers, never a request body, never the token.

## Security

- Bind `127.0.0.1` only, confirmed by direct inspection of `server.py` and
  by the real end-to-end test below.
- Every query parameter passes through `safe_query_param()`: bounded to
  4096 chars, rejects control characters, never reaches a shell or `eval`.
- No route ever shells out or executes anything from a request.
- A handler exception is caught and returns `500 {"error": "internal_error"}`
  — the server thread survives a bad request.

## Development setup

```powershell
cd vscode-extension
npm install
npm run compile        # tsc -p ./
```

Press F5 in VS Code (with `vscode-extension/` open) to launch an Extension
Development Host with the extension loaded. Package a `.vsix` for local
install with `npx @vscode/vsce package` (not published to the Marketplace
— out of scope for this phase).

### Running the Python service tests

```powershell
python -m pytest tests/test_service.py -v
```

### Running the extension's own test suite

```powershell
cd vscode-extension
npm test
```

**Known limitation**: in this development environment, `@vscode/test-electron`'s
downloaded VS Code test binary was missing its `resources/app` payload on
every attempt (reproduced twice, fresh downloads both times) — an
environment/network artifact, not a defect in the test files themselves,
which compile cleanly and cover every item in the required checklist
(activation, command registration, service discovery, health check,
connected/offline state, reconnection, workspace identity, signal watcher,
panel rendering). The real interactive Extension Development Host (`F5`,
or `code --extensionDevelopmentPath=...`) is unaffected by this and was
used for the actual end-to-end verification instead.

## Troubleshooting

- **Status bar stuck on Offline**: confirm the desktop app is running and
  check `%USERPROFILE%\.claude_code_coach\service.json` exists. If it's
  missing, the service failed to bind (check the desktop app's log for a
  "Coach service could not bind" warning — usually another process already
  holds port 47823).
- **Panel shows stale data**: click **Claude Code Coach: Open Coach** again
  (Command Palette) to force a refresh, or check that
  `claudeCodeCoach.pollIntervalSeconds` isn't set unreasonably high.
- **Firewall prompt on desktop app startup**: not observed on this machine
  (see Real end-to-end verification below) — loopback-only listeners
  typically don't trigger Windows Firewall prompts, since those exist for
  listeners reachable from other hosts.

## Real end-to-end verification (performed this session)

Using an isolated fake `%USERPROFILE%` (so no real user data was touched):
started the real desktop app, confirmed `service.json` was written with a
real port/token, launched the real installed VS Code
(`code --extensionDevelopmentPath=vscode-extension <folder>`), ran
**Claude Code Coach: Open Coach**, and confirmed the panel showed the real
workspace path, `Ready` connection state, and real (empty) session/
environment data — screenshotted. Fired real `hook_receiver.py` events for
that exact workspace `cwd` and confirmed the already-open panel updated
itself live (prompts count and last-event timestamp changed) with no
command re-run, purely from the signal-file watcher. Closed the desktop
app gracefully (`WM_CLOSE`) and confirmed the panel switched to "Coach
service is not running." Restarted the desktop app (new PID, new
token) and confirmed the extension reconnected automatically — no VS Code
reload needed — and the panel repopulated with the same session's data.

No Windows Firewall or Defender prompt appeared at any point during this
process — consistent with `127.0.0.1`-only listeners not being flagged the
way an externally-reachable listener would be.

## Phase 3B: real-time coaching interventions

> **These are heuristic, evidence-based coaching signals — not proof that
> Claude Code made a mistake.** Every warning is generated only from
> `RuntimeSignal`s the existing V5 `runtime_analyzer.py` already computes
> from real observed hook events (see Phase 1/3 above). No new analysis
> logic, no new "overall score", and no Python file was touched to build
> this layer — see "V5 changes" below.

### What's new

- A native VS Code notification when a HIGH-confidence signal is the
  current primary signal for this workspace's session.
- A `Coach: Attention` status-bar state, distinct from `Ready`/`Offline`/
  `Paused`.
- `Claude Code Coach: Pause Coaching` / `...Resume Coaching` commands.
- Action buttons on the panel's "Current Coaching" card for signals that
  have a concrete next step.
- Two new settings (`claudeCodeCoach.coaching.*`) and deterministic,
  documented deduplication so the same warning is never spammed.

### Tier mapping (no new scoring system)

`RuntimeSignal.level` — V5's own field — **is** the product tier. Nothing
in the extension recomputes or overrides it:

| V5 `level` | Product tier | Panel | Status bar | Native notification |
|---|---|---|---|---|
| `high` | HIGH — action needed | Leading coaching card | `Attention` | Yes, unless `notificationLevel` is `off` |
| `medium` | MEDIUM — consider changing | Leading coaching card (no `Attention` promotion) | stays `Ready` | Only if `notificationLevel` is `highAndMedium` |
| `low` | LOW / positive | Leading card or "N more signal(s)" list | stays `Ready` | Never, regardless of settings |

**Honest note on `verification_missing`**: `runtime_analyzer.py`'s
`verification_signal()` always emits this at `level="medium"`, never
`"high"` (see `tests/test_v5.py`). It therefore surfaces as a MEDIUM-tier
coaching event here too — panel card and no `Attention` promotion unless
the user opts into "High + Medium" notifications. This is a deliberate
choice to respect V5's own confidence rating rather than have the
TypeScript layer second-guess it with a per-kind override.

### Priority selector

`pickPrimarySignal()` in `src/coaching.ts` sorts by `level` (high > medium
> low) and returns one signal — the same function the panel and the
background notification path both call, so there is exactly one selector,
not two. Signals never combine into a new number; the loser signals stay
visible underneath in the panel's "N more signal(s)" list.

### Notification rules

`shouldNotify()` (`src/coaching.ts`) is the exact, deterministic rule:

1. Paused → never.
2. `claudeCodeCoach.coaching.notificationsEnabled` is `false` → never.
3. `level: "low"` (including every positive signal) → never, regardless of
   settings — the spec is explicit that routine/positive events must not
   interrupt.
4. `level: "high"` → notify unless `notificationLevel` is `"off"`.
5. `level: "medium"` → notify only if `notificationLevel` is
   `"highAndMedium"`.
6. Already notified for this exact (workspace, session, signal kind)
   within the dedup window → never (see below).

The notification text is one line: `"Claude Code Coach: ⚠ " + signal.message`
— V5's own message, never a fabricated paragraph. It carries two actions,
**View Details** (opens/focuses the Coach panel) and **Dismiss**; either
one, or simply closing the toast, has the same effect — the dedup entry is
recorded at send time, so the toast never repeats within the window
regardless of how it was closed. Dismissing a notification never hides the
signal from the panel — the panel always reflects the latest real state.

### Deduplication

`CoachingStateStore` (`src/coachingState.ts`) keys each notification by
`workspaceFolder :: sessionId :: signal.kind` and stores only a last-sent
timestamp — **never prompt text or file content**. The window is a
documented constant, **15 minutes**
(`coachingState.DEDUPE_WINDOW_MS`). A different kind, a different session,
or a different workspace is never suppressed by another key's entry.
Signals are not tracked on a timer — the primary signal is always
recomputed fresh from the latest `/session` response, so a warning
disappears from the panel/status-bar the moment V5 stops reporting that
`kind` (e.g. `verification_missing` is replaced by `verification_done` the
moment V5 observes a test run; `broad_exploration` disappears once enough
narrowing has happened for V5 to stop flagging it).

### Status bar states

| State | Meaning | Icon |
|---|---|---|
| `Ready` | Connected, no HIGH-tier signal active | `$(check)` |
| `Attention` | A HIGH-tier signal is the current primary signal | `$(alert)`, warning background |
| `Offline` | Desktop app/service unreachable | `$(circle-slash)`, warning background |
| `Paused` | User ran Pause Coaching | `$(debug-pause)` |

Every state uses a distinct icon glyph (not color alone), so Attention and
Offline stay distinguishable regardless of theme.

### Pause / Resume

`claudeCodeCoach.pauseCoaching` / `claudeCodeCoach.resumeCoaching` flip a
boolean in `context.globalState`. **Scope note (deliberate, not an
oversight)**: `globalState` is one store per extension per machine, so
Pause is machine-wide — every VS Code window on this machine, not just the
current workspace. While paused: no notifications, no `Attention` status,
and the panel shows a clear "⏸ Coaching paused" notice in place of the
intervention card. Runtime event collection itself is entirely unaffected
— it's still governed by the existing V5 hook-installation setting, per
the spec's explicit instruction not to silently disable hooks. The full
signal list remains visible (collapsed) under the paused notice, so pausing
suppresses the *interruption*, never the underlying evidence.

### Action buttons

Added to the panel's primary coaching card only where a concrete next step
exists — never filler advice:

| Signal kind | Action(s) |
|---|---|
| `broad_exploration` | **Inspect Prompt**, **View Session** |
| `context_noisy`, `context_growth`, `verification_missing` | **View Session** |
| `skill_underused` (with a resolvable `evidence.skill` match in the environment scan) | **View Skill** |
| anything else | none |

None of these execute the suggestion automatically — they only open the
relevant panel section or the real file V5 already found.

### Configuration

| Setting | Default | Meaning |
|---|---|---|
| `claudeCodeCoach.coaching.notificationsEnabled` | `true` | Master switch for native notifications. |
| `claudeCodeCoach.coaching.notificationLevel` | `"highOnly"` | `"highOnly"` \| `"highAndMedium"` \| `"off"`. |

### Privacy

No change to the local-first architecture: no cloud API, no telemetry, no
new external calls. `CoachingStateStore` persists only signal `kind`
strings, workspace folder paths, session ids, and timestamps in VS Code's
own `globalState` — never prompt text, file content, or anything from a
notification's message beyond what the panel already displays.

## Phase 4B: the extension no longer assumes the desktop app

**The desktop GUI is no longer a prerequisite.** The extension already
discovered "whichever service wrote `service.json`" from Phase 2 onward —
`coachClient.ts` never actually checked *which* process that was — but its
messaging and one real behavior still assumed the desktop app specifically.
Both are fixed this phase, with no change to `app.py` or any other
desktop-side file:

1. **Stale discovery is now actually detected (Step 3/4).**
   `readDiscovery()` now verifies the reported `pid` is a live process
   (`windowRegistry.ts`'s existing `isProcessAlive()`, reused rather than
   duplicated) and that `api_version` is one this client understands,
   before ever returning a usable discovery result. Either failure is
   reported through a new `getLastDiscoveryIssue()` — surfaced in both the
   status bar's offline tooltip and the panel's offline message — instead
   of the generic "Offline" covering three different real situations
   ("nothing has run yet" vs. "the process that wrote this file was killed
   and left it behind" vs. "this service speaks a version I don't"). A
   real forcefully-killed standalone service (Phase 4A's own scenario) was
   used to verify this end to end this session: `service.json` was left
   behind, and both the Python-side `read_discovery_file()` and the
   TypeScript-side `readDiscovery()` correctly reported it as stale.

2. **`openDesktopCoach()` no longer conflates "a service is reachable"
   with "the desktop app is running" (Step 15, a real bug fix).** Prior
   versions showed "desktop app is already running" whenever *any* Coach
   service answered — which became actively wrong once a standalone
   service could be the one answering instead. The command now always
   gives the same honest guidance ("start the desktop app from wherever
   you normally launch it"), since the discovery contract has no field
   that distinguishes a desktop-embedded service from a standalone one,
   and inventing one wasn't necessary to fix the actual bug.

3. **Desktop-specific wording removed from status bar / panel / error
   messages** (`statusBar.ts`, `coachPanel.ts`, `extension.ts`'s
   `inspectPrompt`) — "Coach service" replaces "desktop app" throughout,
   since either process satisfies every one of these states identically.

**Everything else was already desktop-agnostic and needed no change**:
`coachClient.ts`'s HTTP layer, `fileSignal.ts`'s signal-file watcher,
notification/dedup logic (`coaching.ts`/`coachingState.ts`), Pause/Resume,
and the status bar's Ready/Attention/Paused states all already operated
purely on the discovery file + HTTP responses, with no branch anywhere
that checked "is this the desktop." Phase 3B's full notification behavior
(tier mapping, 15-minute dedup, quiet-by-default) is unchanged and was not
touched.

**Verified this session, with the desktop GUI never opened**: a real
`python -m claude_code_coach.service` process, real `hook_receiver.py`
hook events, a real drain into SQLite, and a real Node.js HTTP client
(mirroring `coachClient.ts`'s own request logic) reading the real
`service.json` and getting back real `/api/v1/health` and `/api/v1/session`
responses — including a session whose `cwd` came from a real `SessionStart`
event. See STANDALONE_SERVICE.md's Phase 4B note and the final report for
the full verification log.

## Known limitations

- The service only runs while something (the desktop app, or
  `python -m claude_code_coach.service`, Phase 4A) is running it — there
  is no auto-starting background daemon yet. Steps toward that are
  tracked in STANDALONE_SERVICE.md's "Known limitations."
- **Update (Phase 4C)**: the desktop app now *can* act as a client of a
  standalone service — it checks for one before starting its own embedded
  copy. See [DESKTOP_SERVICE_MIGRATION.md](DESKTOP_SERVICE_MIGRATION.md)
  for what this means for VS Code (nothing — it never depended on which
  process was serving `service.json`) and what's still temporary (the
  embedded copy is not removed; an already-running desktop does not
  retroactively hand off to a standalone service that appears later).
- No automated `npm test` run in this sandboxed environment — the
  downloaded VS Code test binary rejects the test runner's CLI flags here
  (same symptom reproduced across Phase 3B and Phase 4A/4B). New Phase 4B
  tests compile cleanly and were verified by direct code reading plus the
  real (non-mocked) end-to-end check described above; a real interactive
  Extension Development Host run is still the way to close this gap fully.
- No real-time push (WebSocket) — near-real-time via the signal-file
  watcher, typically sub-second in practice but not a hard guarantee.
- Multi-root workspaces use the first folder only.
- The window registry (`windowRegistry.ts`) is written but not yet
  consumed by anything — forward-looking groundwork for a future
  "route a notification to the window that owns this session" feature.
- **Pause is machine-wide, not per-workspace** (Phase 3B) — pausing while
  working in Project A also pauses coaching in every other open VS Code
  window on the same machine. A documented scope choice, not a bug.
- **Notification dedup state is shared across windows on the same
  machine** (Phase 3B) — if the exact same workspace+session is somehow
  open in two windows at once, a notification shown in one suppresses the
  repeat in the other within the 15-minute window. This is the intended
  effect of avoiding duplicate interruptions, not a routing flaw, but is
  worth naming since it differs from a strictly per-window design.
- `@vscode/test-electron`'s automated headless test run could not complete
  in this development environment — reproduced again for Phase 3B (this
  time the downloaded `Code.exe` rejects every CLI flag with `bad option:`,
  a different symptom from the Phase 2 "missing resources/app payload"
  failure, but the same underlying category: this sandboxed environment
  cannot successfully drive the downloaded VS Code test binary). All
  Phase 3B TypeScript compiles cleanly (`tsc -p ./`, zero errors) and the
  full existing + new test suites are written to the same standard as
  Phase 2/3's; they were verified by direct code reading and by mirroring
  Phase 2's precedent of falling back to a real interactive Extension
  Development Host for end-to-end confirmation.
