# VS Code Integration — Architecture & Design Analysis

**Status: DESIGN ONLY. Nothing in this document has been implemented.**
No production file under `claude_code_coach/` was modified to produce this
analysis. See [Final Report](#final-report) at the end for an explicit
confirmation of what was and was not touched.

---

## 1. Current V5 architecture summary

Grounded by re-reading the actual source during this analysis (not
inferred from filenames), as of the V5 baseline (242/242 tests passing,
prompt benchmark 58/58, runtime benchmark 30/30):

```
claude_code_coach/
    app.py                 Qt bootstrap: init_db() -> QApplication -> MainWindow -> app.exec()
    database/
        db.py               sqlite3 access layer. get_connection() opens a FRESH
                             connection per call (context manager) — already
                             thread-safe in the sense that matters: every caller,
                             on any thread, gets its own connection.
        migrations.py        CURRENT_SCHEMA_VERSION = 5. Idempotent, additive
                             migrations (ALTER TABLE / CREATE TABLE IF NOT EXISTS).
    analyzer/                Pure, deterministic, provider-independent.
                             analyze_prompt(text) -> AnalysisResult.
                             prompt_rewriter.suggest_prompt(text) -> PromptSuggestion.
    analytics/                Cross-prompt-history clustering (Skill/Agent/CLAUDE.md
                             candidates), habit trend %.
    providers/                Real, read-only Claude Code environment discovery.
                             ClaudeCodeEnvironmentProvider(project_root, user_home).scan()
                             -> EnvironmentSnapshot (CLAUDE.md/Skills/Agents/MCP).
                             Secret redaction in providers/redaction.py.
    runtime/                  Real Claude Code hook-event observation.
                             hook_receiver.py: the actual command Claude Code
                             invokes (always exits 0, never blocks a real session).
                             event_source.py: HookFileEventSource drains
                             APP_DIR/runtime_events/<session_id>.jsonl via an
                             atomic rename-then-read-then-delete per poll (no
                             in-memory offset — safe across restarts).
                             runtime_analyzer.py: events -> RuntimeSignal
                             (evidence-carrying). session_coherence() ->
                             Context Health %. verification_signal().
                             hook_installer.py: the ONLY code that writes to a
                             real Claude Code settings.json — atomic, additive,
                             never automatic (explicit user confirmation only).
                             runtime_coach.py: RuntimeCoach — orchestrator;
                             .status() returns the CURRENT session (most recent
                             by last_event_at, GLOBALLY — see Finding V5-1 below).
    integration/               Sits ABOVE analyzer + providers + runtime (the only
                             layer allowed to depend on all three).
                             environment_matching.py: prompt <-> DETECTED resource
                             correlation (existing/candidate/none tri-state).
                             approach_advisor.py: recommend_approach(prompt,
                             analysis, environment_snapshot, runtime_status)
                             -> ApproachReport. THE single synthesis point for
                             "what should I do" recommendations.
    creators/                  Pure, Qt-free. validate/render/save Skill and
                             Agent files. Atomic writes, duplicate-name warnings,
                             secret redaction. Never called without explicit
                             confirmation from a UI action.
    ui/                        PySide6. controller.py (CoachController) is the
                             ONE stateful, Qt-bound facade every page talks to —
                             holds live Python objects: ClaudeCodeEnvironmentProvider,
                             RuntimeCoach, an in-memory EnvironmentSnapshot cache,
                             a QThread for async environment re-scans.
main.py                       Entry point. sys.path insert, then app.run().
```

### How a fact currently reaches the screen (traced end to end)

`hook_receiver.py` (external process, spawned by Claude Code) → appends one
JSON line to `~/.claude_code_coach/runtime_events/<session_id>.jsonl` →
`CoachController` (inside the single running desktop process) owns a
`RuntimeCoach` whose `HookFileEventSource` is polled by a `QTimer` **only
while the Sessions page is open** (`ui/runtime.py`'s own 3-second
`QTimer(self)`) or once per `Dashboard.refresh()` call → drained events are
written to the `runtime_events`/`runtime_sessions` SQLite tables →
`RuntimeCoach.status()` re-reads from SQLite and recomputes signals on
demand (nothing is cached beyond one call) → the Qt widget tree re-renders.

**This has one direct consequence for VS Code integration**: today, *only
the desktop app's own QTimer* ever drains `runtime_events/*.jsonl` into
SQLite. If the desktop app is not running, hook events pile up as `.jsonl`
files but are never persisted into queryable state. Any VS Code-facing
service therefore either (a) requires the desktop app to be running (so its
existing drain loop keeps working), or (b) needs its own independent drain
loop — see [Desktop lifecycle behavior](#10-desktop-lifecycle-behavior).

### Existing local file layout (all under `%USERPROFILE%\.claude_code_coach\`)

| Path | Written by | Read by |
|---|---|---|
| `coach.db` | `database/db.py` (all writes) | same |
| `runtime_events/<session_id>.jsonl` | `runtime/hook_receiver.py` (external process) | `runtime/event_source.py` (drained into `coach.db`, then deleted) |

No other local file or socket currently exists. **CONFIRMED** by `grep -rn
"socket\|http.server\|websocket\|named.pipe" claude_code_coach/` returning
nothing.

### Existing entry points

**CONFIRMED**: exactly one — `python main.py` (the PySide6 GUI). There is
**no existing CLI mode, no existing daemon mode, no existing `--headless`
flag**. `hook_receiver.py` is invoked directly by Claude Code (not by a
user), and is not itself a service — it does one write and exits.

### Existing dependencies

**CONFIRMED** (`requirements.txt`): `PySide6>=6.5` only. Everything else
(sqlite3, http.server, json, pathlib, subprocess, tempfile) is Python
stdlib. This is a deliberate, repeatedly-stated project constraint across
every prior version ("don't add dependencies unless necessary").

---

## 2. Investigation: what's actually available in this environment

Rather than assume a Claude Code ↔ VS Code integration mechanism exists,
this machine's real, installed software was inspected directly.

### 2.1 The real "Claude Code for VS Code" extension (`anthropic.claude-code`, v2.1.267 — installed on this machine)

Read its actual `package.json`:

- `main`: `./extension.js` (a bundled/minified JS file — not meaningfully
  reverse-engineerable into a stable contract).
- `activationEvents`: `["onStartupFinished", "onWebviewPanel:claudeVSCodePanel"]`.
- `contributes`: `configuration`, `jsonValidation`, `commands`,
  `keybindings`, `viewsContainers`, `views`, `walkthroughs`, `menus`. **No**
  `api`/exports field is declared for other extensions to consume.
- Its 26 registered commands (`claude-vscode.*` / `claude-code.*`) are all
  **user-facing UI actions** — open panel, new conversation, accept/reject
  proposed diff, insert @-mention, open in terminal, etc. None of them
  return session/runtime data to a caller; VS Code's command API lets any
  extension invoke them via `vscode.commands.executeCommand(id)`, but that
  only *triggers a UI action* in the Claude Code extension — it does not
  hand back structured data, and depending on an unrelated extension's
  internal command IDs (not documented as a public API) is fragile across
  versions.

**Finding**: **NOT CONFIRMED** — there is no documented, stable
programmatic API from the official Claude Code VS Code extension for a
third-party extension to read its session state, runtime events, or
environment info. This app must keep using the same hook-based mechanism
V4 already built (Claude Code CLI's own hooks — which fire identically
regardless of whether Claude Code was launched from this extension's panel,
its integrated terminal command, or a bare terminal, since they're all the
same underlying CLI session/hook system) rather than trying to talk to the
`anthropic.claude-code` extension directly.

### 2.2 Real prior art: `singularityinc.claude-notifier` (v4.5.0 — installed on this machine, and the actual source of 5 of the hook entries already found in this machine's own `~/.claude/settings.json` during V3.1/V4 research)

This is a **published, real, working third-party VS Code extension that
solves an adjacent problem** (desktop notifications on Claude Code
events) using **exactly the same class of mechanism V4 already built
independently**: it registers its own hook scripts into
`~/.claude/settings.json` (`hook/claude-notifier-on-stop.ps1` and
siblings — confirmed by reading the actual files on disk). Two details
from its real, shipped code are directly load-bearing for this design:

1. **Local-only, no-service-by-default signaling.** `_lib.ps1`'s
   `Write-NotifierSignal` writes a **single flat text line**
   (`"$Reason $Timestamp $SessionId $Cwd"`) to one shared signal file —
   no server, no port, no JSON parsing needed on the write side. The
   companion `Test-ExtensionOwnsCwd` function is the **multi-window
   answer**: each running VS Code extension-host instance writes its own
   small file, named by its **own process PID**, into a shared "active
   windows" directory, listing the workspace folder(s) it owns; a hook
   script (or, in this design, a service) determines which window a given
   `cwd` belongs to by checking folder-containment against each
   registered window's file, and skipping any file whose PID process no
   longer exists (`Get-Process -Id $pidVal`) — a robust, dependency-free
   staleness check.
2. **A loopback TCP daemon is used, but only for the SSH/WSL/remote-host
   case** — confirmed by its own `daemon/README.md`: a small Go daemon
   listens on `127.0.0.1:47291` by default, speaking newline-delimited
   JSON, and is explicitly *not* used for local (non-remote) sessions.

**Why this matters for this design**: it is real, running, confirmed
evidence that (a) hook-based local signaling without any server process is
a proven, low-complexity pattern for the "ambient state changed" half of
this problem, and (b) a per-window PID-keyed registry file is a proven,
simple answer to the multi-window correlation problem this document is
asked to address. Both are adopted below, adapted to this project's own
(Python + SQLite, not PowerShell + flat files) architecture.

### 2.3 VS Code extension API facts relied on below

These are treated as **CONFIRMED** — they are core, long-stable,
documented VS Code Extension API surface, not speculative:

- `vscode.window.createStatusBarItem`, `vscode.window.createWebviewPanel`
  and/or a `WebviewViewProvider` registered via `contributes.views` (for a
  sidebar panel, matching the "Coach Panel" requirement more naturally
  than a floating webview tab).
- `vscode.commands.registerCommand` / Command Palette contribution via
  `contributes.commands`.
- `vscode.workspace.workspaceFolders` (multi-root aware — an array, not a
  single folder) and `vscode.workspace.onDidChangeWorkspaceFolders`.
- `vscode.workspace.createFileSystemWatcher` for watching a local
  directory/file for changes.
- `vscode.ExtensionContext.subscriptions`, `.globalState`,
  `.workspaceState` for extension-local persistence (e.g. a pause/resume
  flag), and `.extensionPath`/`.extensionUri` for bundled assets.
- The Extension Host is a real Node.js process with full built-in `http`/
  `net`/`fs` module access — a `GET`/`POST` to `http://127.0.0.1:<port>/...`
  is completely standard from within a VS Code extension.
- **Node/npm/`vsce`/VS Code CLI tooling actually present on this machine**
  (checked directly): `node v24.15.0`, `npm 11.12.1`, `code 1.132.0`. This
  means Phase 2 implementation and compilation can be verified for real on
  this machine, not just written blind.

---

## 3. Proposed VS Code architecture

```
                         Claude Code CLI
                               │
                        existing hooks (V4, unchanged)
                               │
                               ▼
                    hook_receiver.py (unchanged)
                               │
                   APP_DIR/runtime_events/*.jsonl (unchanged)
                               │
              ┌────────────────┴────────────────┐
              │  Claude Code Coach (desktop)     │
              │  existing QTimer-driven drain    │  <- unchanged
              │  (ui/runtime.py, Dashboard)      │
              │            │                     │
              │            ▼                     │
              │        coach.db (SQLite)         │  <- unchanged schema,
              │            │                     │     +1 additive column
              │            ▼                     │     (see Finding V5-1)
              │  NEW: service/coach_service.py   │  <- thin, Qt-free facade
              │  NEW: service/http_server.py     │     reusing analyzer/
              │  (127.0.0.1, stdlib http.server,  │     runtime/providers/
              │   started/stopped by app.py)      │     integration AS-IS
              └────────────────┬─────────────────┘
                               │
                   loopback HTTP  +  file-watch nudge
                   (see §4/§5 below)
                               │
              ┌────────────────┴────────────────┐
              │                                 │
              ▼                                 ▼
     Desktop Coach (existing)          VS Code Extension (NEW)
     unchanged UI, unchanged            vscode-extension/
     controller, still the                thin TypeScript client
     primary/full-featured app            status bar + panel + commands
```

The desktop application's **existing** `CoachController` (Qt-bound,
single-threaded-by-design, owns a live `QThread` for async scans) is
**not** reused directly by the HTTP layer — see §4.4 for why, and why that
is not "a second implementation."

---

## 4. Communication mechanism comparison

Evaluated against the criteria requested: Windows support, reliability,
security, implementation complexity, latency, dependency cost, offline
operation, maintenance, live-signal delivery, on-demand state queries,
survival across desktop restarts, multi-window support.

### Option A — localhost HTTP

- **Windows support**: full; `http.server` (stdlib) works identically on
  Windows/macOS/Linux.
- **Reliability**: high — plain request/response, no persistent connection
  to manage or reconnect.
- **Security**: bind `127.0.0.1` only (never `0.0.0.0`); add a random
  per-launch shared-secret token (see §11) as defense-in-depth against
  other local users/processes on a shared machine.
- **Complexity**: low. `http.server.ThreadingHTTPServer` + a
  `BaseHTTPRequestHandler` subclass, entirely stdlib. Client side: Node's
  built-in `http` module (no npm dependency required at all for the
  client, though a tiny convenience wrapper is reasonable).
- **Latency**: sub-millisecond on loopback for small JSON payloads.
- **Dependency cost**: **zero** new Python dependencies; **zero** required
  npm dependencies for the HTTP client itself (only dev-time deps: the
  `@types/vscode`/`@vscode/vsce` tooling needed to build any extension at
  all).
- **Offline**: yes — loopback traffic never leaves the machine.
- **Maintenance**: low — a handful of JSON endpoints with a stable schema.
- **Live signals**: good with polling (matches what the desktop app's own
  Sessions page already does — a 3s `QTimer`); can be made near-instant
  when combined with §4.5 below.
- **On-demand queries**: this is HTTP's natural strength — "analyze this
  prompt text right now" is a clean `POST`.
- **Survives desktop restarts**: no by itself — the service is embedded in
  the desktop process (see §10 for exactly how this is handled and why
  that's the right tradeoff, not a gap).
- **Multi-window**: each request carries its own `project_root`/`cwd`; the
  service is otherwise stateless per request (see §8).

### Option B — localhost WebSocket

- Would provide true server-push instead of poll/watch-then-refetch.
- **Complexity/dependency cost is the deciding factor against it for v1**:
  a correct WebSocket **server** in pure Python stdlib is nontrivial to
  implement correctly (handshake, framing, ping/pong) — realistically
  needs a dependency (`websockets` or similar), which conflicts with the
  project's repeated "no new dependencies unless necessary" constraint.
  On the client side, VS Code's bundled Extension Host Node version is not
  confirmed to include a global `WebSocket` (Node only added it as stable
  fairly recently); the safe choice would be the `ws` npm package — a
  small but real added dependency.
- **Verdict**: not justified for v1 given Option A + §4.5 delivers
  comparable practical latency for a coaching tool (not a real-time
  editor feature) at zero dependency cost. Documented as a **future
  upgrade path**, not adopted now.

### Option C — Windows named pipe / IPC

- Windows-only by construction (or needs platform-specific code paths for
  any future cross-platform ambition), needs either a native Node addon
  or manual `net.Socket` pipe-path handling on the client, and a
  platform-specific server implementation in Python (`win32pipe` needs
  `pywin32`, itself a new dependency not currently present). More
  implementation complexity than Option A for no concrete benefit over
  loopback HTTP in a single-user local scenario.
- **Verdict**: rejected — higher complexity and dependency cost, no
  meaningfully better security or reliability than 127.0.0.1 HTTP for this
  use case.

### Option D — filesystem/event stream only (no service process)

- Directly inspired by the confirmed `claude-notifier` prior art (§2.2).
  Excellent for **ambient, push-style "something changed" signaling** —
  cheap, dependency-free, proven.
- **Insufficient alone** for the request/response half of this product
  (Prompt Inspector, Approach Advisor need "here is text, analyze it and
  hand back a structured report" — a pure file-drop protocol for that is
  higher latency and more fragile than a direct call: it would mean
  writing a request file, then polling for a correspondingly-named
  response file to appear, with timeout/cleanup logic to invent from
  scratch).
- **Verdict**: not sufficient as the *only* mechanism, but its proven
  "shared signal + PID-keyed window registry" pattern is adopted
  **alongside** Option A — see §4.5.

### Option E — CLI bridge (spawn a short-lived Python process per request)

- Would avoid needing a long-running service at all (e.g.
  `python -m claude_code_coach.cli analyze "<prompt>"` returning JSON on
  stdout), at the cost of ~100-300ms Python interpreter startup latency
  per call (measurable, not free) and re-opening the SQLite connection
  and re-running environment discovery from scratch on every single
  keystroke-adjacent interaction — poor fit for "analyze as I type"-style
  UX the desktop app itself already provides via a debounced live
  analyzer.
- **Verdict**: rejected as the primary mechanism (too slow for
  interactive use); could be a reasonable *fallback* when the embedded
  service isn't running and the user explicitly asks for a one-off
  analysis — not designed further here since it isn't needed if Option A
  is available, and this document must recommend one primary mechanism.

### 4.5 Recommended: **Option A, augmented with the proven Option D signal file**

**Primary**: loopback HTTP (127.0.0.1, stdlib-only on the Python side, a
small dependency-free TypeScript client) for every request/response
operation: environment queries, prompt analysis, approach recommendations,
session/context-health queries, pause/resume.

**Augmentation, not a second mechanism**: the service also maintains one
small **signal file** (`APP_DIR/vscode_signal.txt`, written on every
processed hook event — same one-line-of-text idea as `claude-notifier`'s
`$LibSignalFile`, adapted) that the extension watches via
`vscode.workspace.createFileSystemWatcher`. On a change event, the
extension simply **re-fetches** `/session` over HTTP immediately instead
of waiting for its next poll tick — turning a "poll every 3-5s" baseline
into "near-instant on real events, poll as a fallback." This costs nothing
new on the Python side (one extra small file write, reusing the exact
"write a line to a shared file" pattern already proven in the wild) and
nothing new as a dependency on the TypeScript side (`createFileSystemWatcher`
is core VS Code API).

---

## 5. Recommended architecture (detail)

```
Python side (new, additive package):
    claude_code_coach/service/
        __init__.py
        coach_service.py     Qt-free façade: thin functions/class wrapping
                              analyzer.analyze_prompt, prompt_rewriter.suggest_prompt,
                              integration.recommend_approach,
                              providers.ClaudeCodeEnvironmentProvider(...).scan(),
                              runtime.runtime_coach.RuntimeCoach(...).status(),
                              database.db.* — the SAME calls ui/controller.py
                              already makes, just without any Qt/QThread coupling,
                              so it's safe to call from the HTTP server's
                              worker threads.
        http_server.py        http.server.ThreadingHTTPServer subclass +
                              BaseHTTPRequestHandler routing table. Binds
                              127.0.0.1 only. Started on a plain Python
                              `threading.Thread` (NOT a QThread — it never
                              touches a QObject) from app.py, right after
                              init_db() and before window.show(). Stopped on
                              QApplication.aboutToQuit.
        discovery.py           Writes/removes APP_DIR/service.json
                              ({"port", "token", "pid", "started_at"}) so the
                              extension can find the service without a
                              hardcoded port assumption.

TypeScript side (new, separate directory, does not touch Python packaging):
    vscode-extension/
        package.json           contributes: commands, a status bar item
                              (declared programmatically, not via package.json),
                              a sidebar view container + WebviewViewProvider,
                              configuration (settings).
        src/
            extension.ts        activate()/deactivate(); wires everything below.
            coachClient.ts       reads APP_DIR/service.json, makes HTTP calls,
                              handles "service unavailable" uniformly.
            fileSignal.ts        wraps the vscode_signal.txt file watcher.
            statusBar.ts
            coachPanel.ts        WebviewViewProvider for the sidebar panel.
            windowRegistry.ts    writes this VS Code window's PID + owned
                              workspaceFolders into
                              APP_DIR/vscode_windows/<pid>.json on activate,
                              removes it on deactivate — the confirmed
                              claude-notifier pattern, adapted to JSON.
            types.ts             TS mirrors of the JSON contracts in §6.
```

### Why the HTTP layer does not duplicate `ui/controller.py`

`CoachController` is deliberately Qt-shaped: it owns a live `QThread` for
async environment scans, a `_navigation_callback` for cross-page routing,
and page-registration/`refresh_all()` plumbing that only makes sense with
a Qt widget tree. None of the actual *intelligence* lives there — every
method is a thin call into `analyzer`/`runtime`/`providers`/`integration`.
`coach_service.py` calls the **exact same underlying functions**
(`analyze_prompt`, `suggest_prompt`, `recommend_approach`,
`ClaudeCodeEnvironmentProvider(...).scan()`, `RuntimeCoach(...).status()`)
directly — it duplicates only the thin "which function do I call for this
request" wiring (a handful of lines per endpoint), the same category of
duplication that already exists, by design, between `ui/controller.py`
and any future non-Qt caller. **No prompt analysis, environment discovery,
runtime interpretation, or approach logic is reimplemented anywhere.**

### Threading/SQLite safety

`database/db.get_connection()` already opens a **fresh sqlite3 connection
per call** via a context manager — this is the existing pattern every
current caller (including multiple Qt pages) already relies on. An HTTP
handler thread calling into `coach_service.py` gets its own connection the
same way; SQLite's own file-level locking handles the rest. No new
concurrency primitive is required. The one thing the HTTP layer must
**not** do is touch a live `QObject` from a non-Qt thread — hence
`coach_service.py` never imports anything from `ui/`.

---

## 6. Data contract proposal

All endpoints: `GET`/`POST` under `http://127.0.0.1:<port>/`, JSON in/out,
`X-Coach-Token: <token>` header required (see §11), `Content-Type:
application/json`. Every response distinguishes DETECTED / POSSIBLE /
INFERRED / UNKNOWN exactly as the existing desktop UI already does — no
new vocabulary invented.

| Endpoint | Method | Request | Response (shape) | Backed by (existing, unmodified) |
|---|---|---|---|---|
| `/status` | GET | — | `{connected, version, project_root_default}` | trivial |
| `/environment` | GET | `?project_root=` | `EnvironmentSnapshot` JSON (cached, from DB) | `db.fetch_environment_snapshot()` |
| `/environment/scan` | POST | `{project_root}` | same, freshly scanned | `ClaudeCodeEnvironmentProvider(...).scan()` |
| `/analyze` | POST | `{prompt}` | `AnalysisResult` JSON | `analyzer.analyze_prompt` |
| `/suggest` | POST | `{prompt}` | `PromptSuggestion` JSON | `analyzer.prompt_rewriter.suggest_prompt` |
| `/approach` | POST | `{prompt, project_root?}` | `ApproachReport` JSON | `integration.recommend_approach` |
| `/session` | GET | `?project_root=` or `?cwd=` | `RuntimeStatus` JSON (see Finding V5-1) | `RuntimeCoach.status()` |
| `/session/events` | GET | `?session_id=&limit=` | recent `RuntimeEvent`s | `db.fetch_runtime_events` |
| `/runtime/pause` | POST | — | `{runtime_enabled: false}` | `controller.set_runtime_enabled` equivalent |
| `/runtime/resume` | POST | — | `{runtime_enabled: true}` | same |

**Explicitly NOT exposed over HTTP in v1** (see §11): installing/removing
hooks, saving a Skill/Agent, clearing data, changing `project_root`
globally. These remain desktop-only, confirmation-gated actions. The
extension's role for these is to **open the desktop app** (a "Open Desktop
Coach" command), not to perform them itself.

---

## 7. Runtime event flow (VS Code's view of it)

1. Claude Code fires a hook (unchanged, V4 mechanism).
2. `hook_receiver.py` appends one JSONL line (unchanged).
3. The desktop app's existing drain loop (QTimer, unchanged) persists it
   to `coach.db` **the next time it ticks** (today: only while the
   Sessions page is open, or on a Dashboard refresh — see Finding V5-2).
4. `coach_service.py` additionally touches `vscode_signal.txt` right after
   a successful drain (new, small addition to the existing drain path —
   see §16 for exactly where).
5. The extension's file watcher fires → re-fetches `/session` → updates
   the status bar/panel.

---

## 8. Workspace/project mapping

Each VS Code extension host instance knows its own
`vscode.workspace.workspaceFolders` directly — no cross-process lookup
needed for that. Every HTTP request the extension makes includes the
relevant workspace folder path as `project_root` (Environment/Approach
endpoints) or `cwd` (Session endpoint). The service never guesses; if the
parameter is omitted it falls back to the desktop app's own configured
`project_root` setting (so a request from an extension that hasn't
specified one still gets a sensible default, matching how the desktop UI
itself behaves before you pick a folder).

**Multi-root workspaces**: `workspaceFolders` is an array. v1 uses the
first folder as the primary `project_root` for simplicity; a later
iteration could let the panel show a folder picker for genuinely
multi-root setups (documented as a future item, not built now).

---

## 9. Multiple-window behavior

Adopting the confirmed `claude-notifier` pattern (§2.2), adapted to JSON:
on `activate()`, each extension instance writes
`APP_DIR/vscode_windows/<pid>.json` = `{"pid", "folders": [...],
"started_at"}`; on `deactivate()` it deletes its own file. Any consumer
(the service, or the extension itself comparing against siblings) can
enumerate that directory, skip entries whose PID is no longer a live
process, and determine which window(s) currently claim a given `cwd`.

For v1, this registry is **written but not yet required to be read by
anything** — each window's requests are already self-scoped by the
`project_root`/`cwd` it sends. The registry exists so that a *future*
feature (e.g. "route a notification to the specific window that owns
this session" — exactly `claude-notifier`'s own use case) has the
groundwork already in place, without over-building it now.

---

## 10. Desktop lifecycle behavior

| Scenario | Behavior |
|---|---|
| Desktop starts, VS Code starts after | Extension's first `/status` call succeeds once `service.json` exists and is fresh. |
| VS Code starts first, desktop starts later | Extension shows "Coach service unavailable" (§ Error handling below) until the next periodic retry succeeds. |
| Desktop closes | `service.json` removed on `aboutToQuit`; extension's next call fails cleanly → "unavailable." No stale port confusion. |
| Desktop restarts | New `service.json` (new PID, same or new port); extension's discovery re-reads the file each time rather than caching a stale port. |
| VS Code reloads (Developer: Reload Window) | `deactivate()`/`activate()` re-run; window registry file rewritten; no special handling needed. |
| VS Code opens another workspace | `onDidChangeWorkspaceFolders` fires; the extension updates its own registry file and future requests use the new `project_root`. |

**Explicit design choice**: the service's lifecycle is coupled to the
desktop app's process, matching the acceptance demo's own script ("Start
Claude Code Coach desktop application" as step 1, "Close the desktop
service" as step 17). A fully decoupled background service (independent
of whether the GUI window is open) is a reasonable *future* direction but
is **not** assumed or half-built here — see Known limitations.

---

## 11. Security model

- Bind **`127.0.0.1` only** — never `0.0.0.0`. Confirmed as the intended
  posture in the spec; adopted without exception.
- **Shared-secret token**: a random token generated at service startup,
  written into `service.json` (a file with the same OS-account-level
  access as `coach.db` already has — no new exposure), required as an
  `X-Coach-Token` header on every request. This is defense-in-depth
  against another local process/user on a shared machine probing the
  port — not a defense against a co-resident malicious process running as
  the *same* OS user, which could read `service.json` directly anyway
  (an inherent limit of any unauthenticated-by-OS-user loopback service;
  documented, not hidden).
- **Strict request validation**: every endpoint validates JSON shape,
  field types, and payload size *before* passing anything to analyzer/
  runtime/provider code; malformed input returns `400`, never a stack
  trace, never a crash of the drain thread.
- **No command execution surface, ever.** The HTTP layer only ever calls
  pure analysis functions and the existing safe DB read/write wrappers.
  It **never** shells out, never executes anything from a request body,
  and — as stated in §6 — never exposes hook-install, Skill/Agent-save, or
  Clear-All-Data over HTTP at all, specifically because those already
  require an explicit, visible confirmation dialog in the desktop UI, and
  blindly trusting an HTTP body for a file-writing or Claude-Code-config-
  writing action would be a materially larger, unnecessary attack surface
  than anything this feature needs.

---

## 12. Privacy model

Unchanged from V5, extended consistently:

- No cloud API, no external AI API, no telemetry — the extension talks to
  **one place**: `127.0.0.1`, and nowhere else.
- Prompt text sent to `/analyze`/`/suggest`/`/approach` is processed
  **in-memory only** by the same deterministic functions the desktop
  Inspector already uses — it is **not** persisted by the HTTP layer
  itself. Whether the *desktop app's own Inspector* later saves a prompt
  to history is a separate, existing, user-initiated action ("Analyze &
  Save") — the VS Code extension never triggers that save path.
- MCP results are never collected (matches V3.1/V4: the app never connects
  to an MCP server at all).
- Secrets: any text that flows through `/environment` responses has
  already been through `providers/redaction.py` before it ever reaches
  SQLite — the HTTP layer adds no new exposure here, it just serializes
  already-redacted data.

---

## 13. VS Code UX proposal

Matches the spec's own suggested layout closely, using a
`WebviewViewProvider` registered in the Activity Bar / Explorer sidebar
(not a floating tab) so it behaves like a persistent panel rather than
something that has to be reopened:

```
Claude Code Coach

┌─────────────────────────────────┐
│ ● Connected                     │
│ Project: my-project             │
└─────────────────────────────────┘

CURRENT SIGNAL
⚠ Broad exploration detected
This task appears narrow.
Suggested: Search → narrow → read → modify

APPROACH
✓ Existing Skill detected  [View Skill]

SESSION
Context: Growing    Verification: Needed
[Inspect Session]
```

Status bar: `Coach: Ready` / `Coach: Watching` / `Coach: Attention` /
`Coach: Paused` / `Coach: Unavailable` — each backed by a real, observed
state (`/status` reachable + no active signal / reachable + a live session
observed / reachable + a medium-or-higher signal present / user-paused /
unreachable), never invented.

**Notification discipline**: per the explicit UX principle, no
notification fires for routine events. A VS Code native notification
(`showWarningMessage`, dismissible) is reserved for **high-confidence
signals only** (e.g. `level: "high"` broad-exploration or a repeated
verification-missing pattern), rate-limited, and fully suppressible via
settings — everything else lives quietly in the panel/status bar.

---

## 14. V5 capabilities reused

| V5 capability | Existing implementation | Reusable? | VS Code use |
|---|---|---:|---|
| Prompt analysis | `analyzer.analyze_prompt` | Yes | `/analyze` |
| Suggested Prompt | `analyzer.prompt_rewriter.suggest_prompt` | Yes | `/suggest` |
| Approach Advisor | `integration.approach_advisor.recommend_approach` | Yes | `/approach` |
| Environment discovery | `providers.ClaudeCodeEnvironmentProvider` | Yes | `/environment`, `/environment/scan` |
| Skill detection | part of `EnvironmentSnapshot.skills` + `environment_matching.match_skills` | Yes | folded into `/approach`, `/environment` |
| Agent detection | `EnvironmentSnapshot.agents` + `match_agents` | Yes | same |
| CLAUDE.md detection | `EnvironmentSnapshot.claude_md` + `claude_md_repetition_signal` | Yes | `/environment`, `/approach` |
| MCP detection | `EnvironmentSnapshot.mcp_servers` | Yes | `/environment`, `/approach` |
| Runtime signals | `runtime.runtime_analyzer.analyze_session` | Yes | `/session` |
| Context Health | `runtime_analyzer.session_coherence` | Yes | `/session` |
| Verification Coach | `runtime_analyzer.verification_signal` | Yes | folded into `/session` signals |
| Session state | `RuntimeCoach.status()` | Partially — needs Finding V5-1 | `/session` |
| Skill/Agent creation | `creators/` | **No (by design)** | not exposed over HTTP — desktop-only |
| Hook install/uninstall | `runtime/hook_installer.py` | **No (by design)** | not exposed over HTTP — desktop-only |

---

## 15. Features that must NOT be duplicated

Explicitly, to guard against a second implementation ever creeping in:

- Prompt classification/scoring/rewriting logic — lives only in
  `analyzer/`.
- Environment scanning/parsing (`CLAUDE.md`, `SKILL.md`, agent `.md`,
  `.mcp.json`, `~/.claude.json` project registry) — lives only in
  `providers/claude_code_provider.py`.
- Hook payload interpretation, session summarization, signal computation —
  lives only in `runtime/runtime_analyzer.py` and `runtime_coach.py`.
- Skill/Agent/CLAUDE.md tri-state matching — lives only in
  `integration/environment_matching.py`.
- File writing for Skills/Agents, hook install/uninstall — lives only in
  `creators/` and `runtime/hook_installer.py`, invoked only from the
  desktop UI's explicit-confirmation flows. The extension never gets a
  code path that could write these files.

---

## 16. Files that would eventually be added (Phase 2 — not created now)

```
claude_code_coach/service/__init__.py
claude_code_coach/service/coach_service.py
claude_code_coach/service/http_server.py
claude_code_coach/service/discovery.py
tests/test_service.py

vscode-extension/package.json
vscode-extension/tsconfig.json
vscode-extension/src/extension.ts
vscode-extension/src/coachClient.ts
vscode-extension/src/fileSignal.ts
vscode-extension/src/statusBar.ts
vscode-extension/src/coachPanel.ts
vscode-extension/src/windowRegistry.ts
vscode-extension/src/types.ts
vscode-extension/media/ (webview CSS/icons)
vscode-extension/test/ (extension tests, per VS Code's @vscode/test-electron)
vscode-extension/README.md
docs/DESKTOP_VSCODE_BOUNDARY.md   (the short developer doc the spec also asks for)
```

## 17. Files that should remain untouched

Everything under `analyzer/`, `analytics/`, `creators/`, `integration/`,
`providers/`, `ui/` (except the two small, additive touches in §18),
`runtime/hook_receiver.py`, `runtime/event_source.py`,
`runtime/event_parser.py`, `runtime/hook_installer.py`,
`runtime/runtime_analyzer.py`, all of `tests/` (only additive new test
files, never edits to existing ones), `main.py`, `requirements.txt`,
`claude_coach.py` (the old V2 prototype, already untouched since V3).

## 18. Minimal, additive V5 touches this would eventually need

Kept as small and separable as possible; **none implemented in this
phase**:

- **`app.py`**: ~4 lines — start the service thread after `init_db()`,
  stop it on `aboutToQuit`. No existing line changed, only new lines
  added.
- **`database/migrations.py`**: one additive column,
  `ALTER TABLE runtime_sessions ADD COLUMN cwd TEXT NOT NULL DEFAULT ''`,
  populated from the `SessionStart` event's `metadata["cwd"]` when
  available — see Finding V5-1. `CURRENT_SCHEMA_VERSION` would bump to 6.
  Fully backward compatible with existing V5 databases (idempotent,
  existing rows simply get an empty string, `db.list_runtime_sessions()`'s
  existing callers are unaffected since they don't reference the new
  column).
- **`ui/settings.py`**: one new small section — "VS Code Integration:
  enable/disable the local service" toggle plus a read-only display of
  the current port, following the exact pattern already used for the
  Runtime/Workshop toggles.

---

## 19. Dependencies required

**Python side: zero new dependencies.** `http.server`, `threading`,
`secrets` (for the token), `json` — all stdlib, consistent with every
prior version's constraint.

**TypeScript side** (a new, separate `package.json` — does not touch the
Python project's dependency surface at all):
- `@types/vscode`, `@types/node`, `typescript` — dev-only, standard for
  any VS Code extension, unavoidable.
- Runtime dependencies: **none required** — Node's built-in `http` module
  is sufficient for the HTTP client; `vscode.workspace.createFileSystemWatcher`
  is core API. `@vscode/vsce` (dev-only) for packaging.

---

## 20. Risks

- **Finding V5-1** (session/cwd correlation gap) must be addressed before
  `/session` can be trusted in a genuine multi-window/multi-project
  scenario — documented, not yet fixed.
- **Finding V5-2** (drain loop only runs while the desktop app's relevant
  page is open or on a Dashboard refresh) means a service request could
  see stale runtime data if the user hasn't touched the desktop UI in a
  while. Mitigation options for Phase 2 (to design then, not now):
  either have `coach_service.py` trigger a drain itself on each `/session`
  call (cheap — draining is just reading small JSONL files), or give
  `RuntimeCoach` its own lightweight background timer independent of any
  Qt page. Leaning toward the former (simpler, no new timer/thread).
- **Port-in-use**: if the configured port is already bound (e.g. another
  local tool), the service should log a warning and simply not start,
  never crash the desktop app over this — the core app must remain fully
  functional with the service disabled.
- **Windows Defender / firewall prompts**: a process binding to a
  loopback-only port on Windows generally does not trigger a firewall
  prompt (those are for listeners reachable from other hosts), but this
  should be verified empirically on this machine during Phase 2, not
  assumed.
- **VS Code Marketplace publishing** is out of scope for this phase and
  likely for the near-term product — the extension would initially be
  installed via a local `.vsix` (`vsce package` + "Install from VSIX"),
  which is sufficient for personal/team use.

---

## 21. Known limitations (of this design, stated up front)

- The service only exists while the desktop app is running — not a
  standalone background daemon. A future version could decouple these;
  this phase deliberately does not.
- No real-time push (WebSocket); "near-real-time" via file-watch-triggered
  re-fetch, typically sub-second in practice but not a hard guarantee.
- Multi-root workspace support is basic (first folder) in v1.
- No token-count/context-window-size telemetry is exposed, because none
  exists anywhere in this app today (consistent with every prior
  version's explicit refusal to fabricate this).
- The window registry (§9) is written but not yet consumed by anything in
  v1 — forward-looking groundwork, not a claimed feature.

---

## 22. Implementation phases (for Phase 2+, not started)

1. **Smallest possible slice**: `service/` package + `/status` endpoint +
   `service.json` discovery + `app.py` wiring. A bare-bones extension that
   only shows Connected/Unavailable in the status bar. Prove the
   loopback round-trip end-to-end with the real desktop app running.
2. Add `/environment`, `/environment/scan` + workspace-aware panel section.
3. Add `/analyze`, `/suggest` + a Prompt Inspector command/panel section.
4. Add `/approach` + Approach Advisor panel section.
5. Add `/session`, `/session/events` + the file-signal nudge (§4.5) +
   Context Health / Verification panel sections. Address Finding V5-1
   (the additive `cwd` column) as part of this phase, since it's needed
   for `/session` to be trustworthy.
6. Add the window registry (§9), pause/resume commands, settings.
7. Error-handling hardening (service unavailable, malformed messages,
   version mismatch) + the full test matrix from §"Testing strategy".
8. Manual end-to-end verification against the *real* desktop app and a
   real VS Code window (not mocks) — mirroring how every prior version of
   this project was verified.

### Testing strategy (for Phase 2+)

- Python: `tests/test_service.py` — HTTP contract tests using
  `http.client`/`urllib` against a service instance bound to an ephemeral
  port (no new test dependency), covering malformed JSON, oversized
  payloads, missing token, wrong project_root, and confirming **zero**
  regressions in the existing 242 tests (run unmodified, unchanged).
- TypeScript: `@vscode/test-electron`-based extension tests (the standard,
  documented VS Code extension testing approach) covering activation,
  service-unavailable handling, malformed response handling, workspace
  detection, and command registration — run headless via `code --version`
  already confirmed available on this machine.
- Integration: a manual (and where feasible, scripted) run of the real
  desktop app + real VS Code window together, mirroring the acceptance
  demo script, with before/after screenshots — the same rigor every prior
  version of this project used, not a mocked substitute.

---

## Final Report

### Repository understanding

Re-inspected the full V5 tree directly (file listing, `requirements.txt`,
a targeted `grep` for any existing socket/HTTP/IPC code, and the exact
`runtime_sessions` schema) rather than relying on memory alone. Confirmed:
one entry point (`main.py`, GUI-only), zero existing IPC of any kind,
`PySide6>=6.5` as the only dependency, and — a concrete, useful finding —
`runtime_sessions` has no `cwd` column today, which matters directly for
the multi-window design.

### Recommended architecture

**Loopback HTTP (127.0.0.1, Python stdlib `http.server`, embedded in the
existing desktop process, started/stopped alongside it)** as the primary
request/response mechanism, **augmented by one small shared signal file**
(watched via `vscode.workspace.createFileSystemWatcher`) for near-real-time
"something happened, re-fetch now" nudges — a pattern directly confirmed
as proven, real-world prior art by reading the actual installed
`claude-notifier` extension's shipped source on this machine, not assumed.

### Why

It's the only option that scores well on every stated criterion
simultaneously: zero new Python dependencies, zero *required* TypeScript
runtime dependencies, full Windows support, low implementation complexity,
sub-millisecond loopback latency, straightforward request/response for the
Prompt Inspector/Approach Advisor's actual on-demand-query need (which a
filesystem-only design cannot serve cleanly), and — combined with the
file-signal augmentation — competitive "live" latency without the real
dependency/complexity cost a WebSocket server would add in pure Python
stdlib. Named pipes and a CLI-bridge were both evaluated and rejected for
concrete, stated reasons (§4), not merely passed over.

### V5 changes required

**No V5 production changes are made in this phase.** For Phase 2, exactly
two small, additive, backward-compatible changes would eventually be
needed (§18): a ~4-line service-start/stop hook in `app.py`, and one
additive `ALTER TABLE runtime_sessions ADD COLUMN cwd TEXT ...` migration
(bumping `CURRENT_SCHEMA_VERSION` to 6) to make session lookups
workspace-aware (Finding V5-1). Both are explicitly deferred, not done now.

### Proposed new files

Listed in full in §16 — a new `claude_code_coach/service/` package (4
files + 1 test file) on the Python side, and an entirely separate
`vscode-extension/` directory (its own `package.json`, not touching the
Python project's dependencies at all) on the TypeScript side, plus this
document and one short follow-up developer doc
(`docs/DESKTOP_VSCODE_BOUNDARY.md`, not yet written — proposed for the
start of Phase 2).

### Existing files to protect

Everything under `analyzer/`, `analytics/`, `creators/`, `integration/`,
`providers/`, `runtime/` (all files), almost all of `ui/`, all of `tests/`
(additive-only), `main.py`, `requirements.txt` — the full list is in §17.

### External assumptions still needing confirmation

- That binding a Python `http.server` to `127.0.0.1` on this Windows
  machine does not trigger a firewall prompt — plausible (loopback
  listeners typically don't), not yet empirically verified.
- That the official `anthropic.claude-code` extension's hook-firing
  behavior (session_id, cwd, event timing) is identical whether Claude
  Code is driven from its own VS Code panel or a bare terminal — inferred
  from architecture (same underlying CLI, same hooks config) but not yet
  directly observed by watching hook events fire while using that
  extension's panel.
- That `service.json`'s OS-file-permission model (same as `coach.db`
  already has) is an acceptable trust boundary for the shared-secret
  token — reasonable given the existing precedent, not independently
  audited.

### Implementation plan

Eight phases, smallest-slice-first, detailed in §22 — starting from a
bare `/status` round-trip with the real desktop app and a real VS Code
window before any coaching feature is added, ending with the full error-
handling matrix and a real (not mocked) end-to-end verification pass.

---

**STOP.** This document is the complete Phase 1 deliverable. No
implementation has occurred; no file under `claude_code_coach/`,
`tests/`, `main.py`, or `requirements.txt` was modified to produce it.
