# VS Code Integration (Phase 2)

Developer reference for the local HTTP bridge between the Claude Code
Coach desktop app and the `vscode-extension/` companion extension. For the
design rationale and alternatives considered, see
[VSCODE_INTEGRATION_ARCHITECTURE.md](VSCODE_INTEGRATION_ARCHITECTURE.md)
(Phase 1). This document covers what was actually built.

## Architecture

```
Claude Code CLI
      │  hooks (unchanged, V4)
      ▼
hook_receiver.py  →  runtime_events/*.jsonl
      │
      ▼
Desktop app (claude_code_coach/service/, started from app.py)
      │
      ├── background drain loop (lifecycle.py) — persists new
      │   hook events into coach.db every 2s, independent of
      │   whether any desktop UI page is open
      │
      └── HTTP server (server.py) — 127.0.0.1 only, token-authed
              │
              ▼
      vscode-extension/ (separate npm project)
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

## Known limitations

- The service only runs while the desktop app is running — not a
  standalone background daemon. A future phase could decouple these.
- No real-time push (WebSocket) — near-real-time via the signal-file
  watcher, typically sub-second in practice but not a hard guarantee.
- Multi-root workspaces use the first folder only.
- The window registry (`windowRegistry.ts`) is written but not yet
  consumed by anything — forward-looking groundwork for a future
  "route a notification to the window that owns this session" feature.
- `@vscode/test-electron`'s automated headless test run could not complete
  in this development environment (see above); the extension was instead
  verified via a real interactive Extension Development Host.
