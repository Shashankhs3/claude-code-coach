# Standalone Coach Service — Architecture Audit (Phase 4, Step 1)

**Status: AUDIT ONLY. Nothing in this document has been implemented.** No
production file under `claude_code_coach/` was modified to produce this
analysis. This is the Step 1 deliverable the Phase 4 spec requires before
any migration code is written.

---

## 1. Baseline (recorded this session, actual run, not assumed)

```
pytest tests/            317 passed
tests/run_benchmark.py    58/58  (prompt rating/task-type/opportunity)
tests/run_runtime_benchmark.py   30/30
vscode-extension  npm run compile     clean, zero errors
vscode-extension  npm test            BLOCKED — same documented environment
                                       issue as Phase 2/3B: this sandbox's
                                       downloaded Code.exe rejects the
                                       test-runner's CLI flags
                                       ("bad option: --no-sandbox" etc,
                                       exit code 9). Not a code regression.
                                       Real verification needs an
                                       interactive Extension Development
                                       Host (F5), same as every prior phase.
```

The spec's own baseline note ("295+ tests") is out of date — the repo has
grown since; 317 is the real current number and the one to protect going
forward.

---

## 2. What already exists (read directly from source, not inferred)

This is the single most important finding of this audit: **Phase 3 already
built almost everything Step 2's process-boundary requires** — it just
runs inside the desktop's Qt process instead of its own. The "intelligence"
layer was already Qt-free before this phase started.

```
claude_code_coach/
    app.py                  Qt bootstrap. init_db() -> QApplication ->
                             MainWindow.show() -> start_service() ->
                             app.aboutToQuit: stop_service() -> app.exec()

    service/                 Already Qt-free end to end — zero PySide6
                             imports anywhere in this package (confirmed
                             by direct read of all 5 files).
        coach_service.py      Façade: health/status/session/environment/
                             analyze/suggest/approach. Each call builds a
                             short-lived RuntimeCoach/EnvironmentProvider
                             and goes straight to database/db.py — same
                             functions ui/controller.py calls, no Qt
                             anywhere in the call chain.
        server.py              http.server.ThreadingHTTPServer subclass,
                             127.0.0.1-only, X-Coach-Token auth, GET routes
                             (health/status/session/environment) + POST
                             routes (analyze/suggest/approach, Phase 3).
        lifecycle.py            THE ONLY file that couples service state to
                             the desktop process: start_service()/
                             stop_service(), service.json read/write, and
                             the 2s background drain-and-signal loop. Uses
                             plain threading.Thread (not QThread) already —
                             i.e. it does not touch Qt either, it is just
                             *started and stopped by* app.py today.
        models.py               JSON response shape builders.

    runtime/
        event_source.py        HookFileEventSource.poll(): atomic
                             rename-then-read-then-delete per session
                             .jsonl file. No in-memory offset — safe to
                             call from any process, at any interval, with
                             zero coordination, by construction (confirmed
                             by direct read — this was already designed
                             for exactly this kind of multi-consumer
                             safety, not repurposed after the fact).
        runtime_coach.py        RuntimeCoach.poll_and_store() /.status()/
                             .install()/.uninstall() — pure orchestration
                             over event_source + database/db.py +
                             runtime_analyzer. Zero Qt imports.
        hook_receiver.py        External process Claude Code invokes
                             directly (unchanged by this phase either way).

    database/db.py             get_connection() opens a FRESH sqlite3
                             connection per call via a context manager.
                             Already safe for concurrent callers on
                             different threads *or different processes* —
                             SQLite's own file locking handles the rest.
                             No process-affinity assumption anywhere.

    ui/controller.py           CoachController — the ONLY place any of this
                             is Qt-shaped: owns a QThread for async
                             environment scans, page-registration/
                             refresh_all() plumbing, a navigation callback.
                             Calls the exact same runtime_coach/analyzer/
                             providers functions coach_service.py calls —
                             confirmed no duplicated intelligence, exactly
                             as docs/VSCODE_INTEGRATION_ARCHITECTURE.md §5
                             already documented and enforced in Phase 2/3.
    ui/runtime.py               Its own QTimer(self), 3s interval, drains
                             via the same RuntimeCoach.poll_and_store() —
                             today this is redundant with lifecycle.py's
                             2s drain loop while the desktop is open
                             (harmless: draining is idempotent by
                             construction, see event_source.py above; the
                             file is gone by the time the second drainer
                             looks for it).
```

### Trace: hook → standalone service → VS Code (as it runs TODAY)

```
Claude Code CLI
    │ hooks fire (unchanged, V4)
    ▼
hook_receiver.py (external process)
    │ appends one JSON line
    ▼
%USERPROFILE%\.claude_code_coach\runtime_events\<session_id>.jsonl
    │
    ▼
claude_code_coach/service/lifecycle.py's _drain_loop()
    (a plain threading.Thread, started by app.py, running inside the
     desktop's OS process — NOT inside the Qt event loop)
    │ every 2s: HookFileEventSource(...).poll() -> RuntimeCoach equivalent
    │           -> db.insert_runtime_event() per event
    ▼
coach.db (SQLite) — runtime_events / runtime_sessions tables
    │
    ├── touched by: lifecycle.py writes vscode_signal.txt on new events
    │
    ▼
service/server.py's CoachHTTPServer (127.0.0.1, token-authed)
    GET /api/v1/{health,status,session,environment}
    POST /api/v1/{analyze,suggest,approach}
    │
    ▼
vscode-extension/ (coachClient.ts reads service.json, polls + watches
                    vscode_signal.txt for near-instant re-fetch)
```

**The desktop UI's own data flow runs in parallel, independently**:
`ui/controller.py`'s `CoachController` holds its own live `RuntimeCoach`/
`ClaudeCodeEnvironmentProvider` instances and an in-memory
`EnvironmentSnapshot` cache; `ui/runtime.py`'s `QTimer` and
`Dashboard.refresh()` each separately call `poll_and_store()` and then
re-read from `coach.db` to repaint Qt widgets. Both paths — the HTTP
service and the desktop UI — ultimately read/write the same `coach.db`
through the same `database/db.py` functions; neither owns the other.

### Existing local file layout (all under `%USERPROFILE%\.claude_code_coach\`)

| Path | Written by | Read by |
|---|---|---|
| `coach.db` | `database/db.py` (all writes, from any caller) | same |
| `runtime_events\<session_id>.jsonl` | `runtime/hook_receiver.py` (external process, per Claude Code session) | `runtime/event_source.py` (drained into `coach.db`, then deleted) |
| `service.json` | `service/lifecycle.py`, written on `start_service()`, removed on `stop_service()` | `vscode-extension/src/coachClient.ts` |
| `vscode_signal.txt` | `service/lifecycle.py`'s drain loop, on every batch of new events | `vscode-extension/src/fileSignal.ts` (file watcher) |

### Existing entry points

**CONFIRMED**: exactly one runnable entry point, `python main.py` (the
PySide6 GUI, which as a side effect starts the embedded HTTP service).
There is **no existing standalone/headless entry point** — `service/` has
no `__main__.py` and is never imported anywhere except from `app.py` and
`tests/test_service.py`.

### Existing dependencies

**CONFIRMED** (`requirements.txt`): `PySide6>=6.5` only; no `psutil`
installed in this environment. `service/` itself already imports nothing
beyond Python stdlib (`http.server`, `threading`, `secrets`, `json`,
`pathlib`, `datetime`) — a real, load-bearing fact for Step 4's stale-PID
detection: no cross-platform "is this PID alive" helper is available for
free, so Phase 4A needs a small stdlib-only one (POSIX: `os.kill(pid, 0)`;
Windows: no equivalent one-liner — needs `ctypes.windll.kernel32.OpenProcess`
or a `tasklist /FI "PID eq <pid>"` subprocess call — evaluated in §6 below,
not decided/implemented here).

---

## 3. What Phase 4A actually needs to change

Given §2, the process-boundary work is much narrower than the spec's own
diagram implies — it is **not** "move the intelligence into a new
process," it's "give the *already-standalone-shaped* `service/` package an
entry point that doesn't require a Qt process to start it, and make its
lifecycle (start/stop/crash-detection) independent of `app.py`."

Concretely, `lifecycle.py`'s coupling to the desktop process is exactly two
things today:

1. `start_service()`/`stop_service()` are only ever **called** from
   `app.py` (`init_db()` → `start_service()` → … → `aboutToQuit` →
   `stop_service()`).
2. `start_service()` returns immediately after spinning up its two daemon
   threads — it relies on the caller (today, `QApplication.exec()`) to
   keep the process alive. A standalone entry point has no such caller, so
   it needs its own blocking wait (a plain `threading.Event().wait()` or
   equivalent, released by a signal handler) instead.

Everything else — the HTTP server, the drain loop, the discovery file, the
signal file, the token auth, the SQLite access — already runs on plain
`threading.Thread`s with zero Qt/GUI dependency and is therefore already
safe to host in a headless process unchanged.

### Proposed Phase 4A shape (design only — not built in this step)

```
claude_code_coach/service/__main__.py   NEW — python -m claude_code_coach.service
    def main() -> int:
        init_db()
        ok = start_service()             # same function app.py already calls
        if not ok: return 1              # port-in-use etc, logged already
        install SIGINT/SIGTERM handlers -> stop_service()
        block until stopped (threading.Event)
        return 0
```

`app.py` is **not modified in this step** and would, per the Absolute
Safety Rule, keep starting its own embedded copy for as long as both paths
need to coexist (Phase 4C decides when the desktop switches to being a
pure client instead). The two are not mutually exclusive today: if a
standalone service is already bound to `DEFAULT_PORT`, `app.py`'s own
`start_service()` call already handles a bind failure gracefully (logs a
warning, returns `False`, desktop app continues normally) — it just means
VS Code integration would be served by whichever process bound the port
first, which is a real, if accidental, preview of Phase 4C's target
behavior and worth calling out as a **already-working fallback**, not a
new risk.

---

## 4. Discovery file evolution (Step 4)

Current schema (`service.json`, written by `lifecycle._write_discovery_file`):

```json
{"port": 47823, "token": "...", "pid": 12345, "started_at": "...", "api_version": "v1"}
```

Needed additions per spec Step 4, without breaking `coachClient.ts`'s
existing reader (which does an unstructured `JSON.parse` and accesses
fields by name — adding fields is backward compatible; nothing existing
needs to change to tolerate them):

- `schema_version` (int, starts at `1`) — lets a future breaking change to
  this file's shape be detected explicitly instead of guessed from
  missing fields.
- `service_version` (string) — the running service's own version, useful
  for a future "desktop is older than the standalone service" warning.
- Everything else (`pid`, `port`, `token`, `started_at`) stays.

**Stale-PID detection** (the actual Step 4 requirement — "do NOT trust a
stale discovery file blindly") needs one new stdlib-only helper, e.g.
`service/lifecycle.py: _pid_is_alive(pid: int) -> bool`. Two real options
on Windows, both stdlib-reachable, neither adds a dependency:

- `ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)`
  → non-null handle means alive; close the handle either way. Fast, no
  subprocess spawn.
- `subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"])` and check
  whether the PID string appears in stdout. Simpler to read, slower
  (spawns a process per check), and locale/format-fragile in a way the
  `ctypes` approach isn't.

Recommendation (for Phase 4A implementation, not decided here): the
`ctypes` approach — it is the one already consistent with this project's
"stdlib only, no new dependency" rule stated repeatedly across every prior
phase, and it's the one used by most dependency-free Windows PID-liveness
snippets for exactly this reason.

A reader (VS Code's `coachClient.ts`, or the desktop's future client code
from Phase 4C) should treat "`service.json` exists but its PID is not
alive" identically to "`service.json` does not exist" — i.e. `Offline`,
never a crash — mirroring the existing `TestServiceUnavailable` test
class's spirit in `tests/test_service.py`.

---

## 5. Runtime event ownership (Steps 5–6)

Already effectively true today, just not yet the *only* drain path: as
shown in §2's trace, `lifecycle.py`'s drain loop already runs independent
of any Qt page being open, and already keeps running as long as the
desktop process is alive — this was Phase 1's own "Finding V5-2" fix,
already shipped. What Phase 4 changes is *whose process* that loop lives
in, not its logic. `ui/runtime.py`'s own `QTimer`-driven
`poll_and_store()` becomes fully redundant once a standalone service is
always running (it already tolerates being redundant today — see §2 — so
no functional change is forced here; whether to remove it is a Phase 4D
cleanup decision, not a Phase 4A one, per the Absolute Safety Rule against
premature removal).

---

## 6. Signal file, HTTP API (Steps 7–8)

No change proposed. `vscode_signal.txt`'s one-line format and
`server.py`'s route table (§ existing docs/VSCODE_INTEGRATION.md) are
already process-agnostic — a standalone process writes/serves them exactly
the same way `lifecycle.py`/`server.py` do today. Backward compatibility
is automatic since nothing about the wire format changes, only which
process produces it.

---

## 7. Desktop as client (Steps 9–13) — scoping note only

Not designed in detail in this step (that's Phase 4B/4C's own design
work), but one architectural fact from this audit matters for that design:
`ui/controller.py` already funnels every page's data access through itself
rather than pages calling `runtime_coach`/`providers` directly (confirmed
by grep — only `controller.py` imports `HookFileEventSource`/
`RuntimeCoach` under `ui/`). This means a future "desktop talks to the
standalone service over HTTP instead of owning its own `RuntimeCoach`"
change has exactly one seam to work through — `CoachController` — not
eleven separate page files. That containment is what makes Step 10's "the
visual experience should remain unchanged initially" realistic rather than
aspirational.

---

## 8. Testing already in place

`tests/test_service.py` (559 lines, 15 test classes) already covers:
startup/shutdown, health, auth/validation, safe query param bounds,
project identification, API versioning, concurrent multi-project requests,
service-unavailable handling, the `cwd` migration, signal-file creation,
and the Phase 3 analyze/suggest/approach POST routes — against a real
`CoachHTTPServer` bound to an ephemeral port. This gives Phase 4A's new
`__main__.py` a real regression harness to extend (new tests: standalone
start/stop via the new entry point, stale-PID detection, schema_version
field) rather than one to invent from scratch.

---

## 9. Risks / open questions carried into Phase 4A design

- Windows PID-liveness needs the small `ctypes` helper above — not yet
  written, not yet verified on this machine.
- Two `start_service()` callers (a standalone process *and* `app.py`, if
  both are ever run at once) will race for `DEFAULT_PORT`; today's
  bind-failure-is-non-fatal behavior already makes this safe, not a new
  hazard, but Phase 4C's design should decide explicitly whether the
  desktop keeps trying to self-start a service at all once a standalone
  entry point exists, or only ever acts as a client.
- `ui/runtime.py`'s redundant `QTimer` drain is harmless today (idempotent
  by construction) but is worth flagging now so Phase 4D's cleanup list
  isn't a surprise later.

---

## Final Report (this step)

### Repository understanding

Re-read `app.py`, all 5 files of `service/`, `runtime/event_source.py`,
`runtime/runtime_coach.py`, `database/db.py`'s connection model,
`ui/controller.py`/`ui/runtime.py`'s import graph, both existing
`docs/VSCODE_INTEGRATION*.md` documents, and `tests/test_service.py`'s
class list directly during this audit — not from memory or filenames
alone.

### Headline finding

The "intelligence" and even the HTTP/discovery/drain layer Phase 4 asks
for **already exist and are already Qt-free** (Phase 3's `service/`
package). The only real Phase 4A work is: (1) a new, small,
`python -m claude_code_coach.service` entry point that calls the same
`start_service()`/`stop_service()` functions `app.py` already calls but
blocks on its own instead of relying on `QApplication.exec()`, and (2) the
stale-PID check Step 4 asks for. Nothing under `analyzer/`, `analytics/`,
`providers/`, `runtime/` (besides possibly retiring the now-redundant
`ui/runtime.py` timer later, not now), `integration/`, or `creators/`
needs to change at all for Phase 4A.

### Baseline recorded

317 pytest passed, 58/58 prompt benchmark, 30/30 runtime benchmark, VS Code
extension compiles cleanly; `npm test` blocked by the same documented
sandbox limitation as Phase 2/3B (not a regression).

### Files that would be added in Phase 4A (proposed, not created in this step)

```
claude_code_coach/service/__main__.py
tests/test_service_standalone.py  (or additions to tests/test_service.py)
```

### Files that should remain untouched in Phase 4A

Everything else — in particular `app.py` stays exactly as-is until Phase
4C's design is written, per the Absolute Safety Rule.

---

**STOP.** This document is the complete Step 1 deliverable. No
implementation has occurred; no file under `claude_code_coach/`, `tests/`,
`main.py`, or `requirements.txt` was modified to produce it.
