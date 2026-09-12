# Standalone Coach Service (Phase 4A)

Developer reference for running the Coach service as its own process,
independent of the desktop GUI. For the design rationale and what was
audited before this was built, see
[STANDALONE_SERVICE_ARCHITECTURE.md](STANDALONE_SERVICE_ARCHITECTURE.md).
For the HTTP API itself (routes, auth, discovery file, signal file), see
[VSCODE_INTEGRATION.md](VSCODE_INTEGRATION.md) — nothing about the API
changed in this phase; only *how the service starts* did.

**Update (Phase 4C)**: the desktop application can now also connect to a
standalone service as a client instead of always starting its own embedded
copy — see [DESKTOP_SERVICE_MIGRATION.md](DESKTOP_SERVICE_MIGRATION.md).
`app.py` checks for a reachable service before starting one; when it finds
one, this process never binds its own port and never starts its own drain
thread, so exactly one process owns draining `runtime_events/*.jsonl` at a
time regardless of how many Coach-aware processes (desktop, standalone,
VS Code) are running.

**Update (Phase 4D-A)**: the desktop can now also *hand off* mid-session —
if it started as the temporary embedded fallback and a standalone service
appears later, it detects this (a periodic check, not instant) and
switches to being a client, releasing its own embedded copy. See
[DESKTOP_SERVICE_MIGRATION.md](DESKTOP_SERVICE_MIGRATION.md) §10 for the
full mechanism and real-process verification, including a genuinely
zero-failure handoff observed by an external HTTP client polling
throughout.

**Operational note from Phase 4D-A's own testing**: if you launch this
process as a subprocess and capture its `stdout`/`stderr` via a pipe, make
sure something actually reads that pipe (or discard it with `DEVNULL`
instead). An unread pipe can fill its OS buffer under load (this process
logs one line per HTTP request) and block this process's next log write —
stalling request handling entirely. Reproduced directly while building
Phase 4D-A's test harness; not a defect in this module, but worth knowing
before wrapping it in a supervisor or launcher script.

## What this is

```
python -m claude_code_coach.service [--port PORT]
```

Runs the exact same `service/coach_service.py` + `server.py` +
`lifecycle.py` HTTP service `app.py` already starts embedded in the
desktop process — same routes, same `service.json`/`vscode_signal.txt`
files, same token auth — but as its own OS process with **zero PySide6
import** anywhere in the chain. Nothing about the service's logic was
duplicated or reimplemented; `service/__main__.py` is a thin wrapper that
calls the same `start_service()`/`stop_service()` functions `app.py`
calls, plus its own wait loop (since there's no `QApplication.exec()` to
keep the process alive) and OS signal handlers for a clean shutdown.

**Result**: `python -m claude_code_coach.service` running alone, with the
desktop GUI never opened, is enough for the VS Code extension to connect —
it discovers `service.json` and calls the HTTP API the same way regardless
of which process wrote the file.

## Starting it

```powershell
cd E:\Claude__Coach
python -m claude_code_coach.service
```

```
2026-09-11 23:28:32 claude_code_coach.service INFO Coach service listening on 127.0.0.1:47823
2026-09-11 23:28:32 claude_code_coach.service INFO Claude Code Coach standalone service listening on 127.0.0.1:47823 (pid 3712). Press Ctrl+C to stop.
```

`--port 0` binds an ephemeral port instead of the default `47823` — used
by the test suite so tests never collide with a real running instance.

If the port is already bound (by the desktop app, or another standalone
instance), `start_service()` returns `False` exactly as it already does
for the desktop app — logged, and this process exits with code `1` rather
than crashing or retrying silently. The already-running service is
unaffected.

## Stopping it

**Ctrl+C** (SIGINT) in the console this process owns triggers a graceful
shutdown: the HTTP server stops, the drain thread joins, `service.json` is
removed. SIGTERM and (on Windows) Ctrl+Break (`SIGBREAK`) do the same.

**Windows note**: sending `SIGTERM` via `os.kill(pid, signal.SIGTERM)` (as
opposed to pressing Ctrl+C in the process's own console) calls
`TerminateProcess` directly on Windows rather than invoking the registered
Python handler — a platform limitation of Windows' signal emulation, not a
bug here. A forceful kill (Task Manager, `taskkill /F`, or SIGTERM sent
this way) skips cleanup and leaves `service.json` behind — this is the
same class of gap `app.py`'s own `aboutToQuit` cleanup already has for a
forcefully-killed desktop app, and it's why **every reader must verify
`service.json`'s PID is actually alive** rather than trusting the file's
mere presence — see the next section.

## Stale discovery-file detection

`service.json` gained two additive fields this phase — `schema_version`
(currently `1`) and `service_version` (the running service's own
`claude_code_coach.__version__`) — and `service/lifecycle.py` gained two
new stdlib-only helpers:

- `pid_is_alive(pid) -> bool` — cross-platform, no new dependency
  (`ctypes.windll.kernel32.OpenProcess` on Windows, `os.kill(pid, 0)` on
  POSIX).
- `read_discovery_file() -> dict | None` — reads `service.json` and
  returns `None` for **both** "file missing" and "file present but its PID
  is dead," so a Python-side caller gets one honest signal instead of
  reimplementing the staleness check itself.

This was verified against a real killed process during this phase: a
standalone service was started, its PID force-killed (`taskkill /F`,
skipping graceful cleanup exactly as documented above), and
`read_discovery_file()` correctly returned `None` for the now-stale file
rather than reporting a dead service as reachable.

**Update (Phase 4B)**: the VS Code extension's own `coachClient.ts` now
performs this same PID-liveness check on its side too (reusing
`windowRegistry.ts`'s existing `isProcessAlive()` rather than a second
implementation) and reports a specific "stale discovery file" diagnostic —
distinct from "nothing is running yet" — via `getLastDiscoveryIssue()`.
See [VSCODE_INTEGRATION.md](VSCODE_INTEGRATION.md)'s Phase 4B section.

## What did NOT change

- `app.py` — the desktop app still starts its own embedded copy of the
  service exactly as before, unmodified. Per the project's Absolute Safety
  Rule for this migration, the embedded path is not removed or altered
  until a later phase (4C/4D) explicitly migrates the desktop to being a
  pure client and that migration is itself verified.
- The HTTP API, `service.json`'s existing fields, `vscode_signal.txt`'s
  format, and every route's behavior — all unchanged. Existing
  `service.json` readers (the VS Code extension) tolerate the two new
  fields without any change on their side (unstructured `JSON.parse`,
  fields accessed by name).
- `runtime/`, `analyzer/`, `providers/`, `integration/`, `database/`,
  `ui/` — none of these were touched. They were already Qt-free below
  `ui/controller.py` (confirmed during the Step 1 audit), so nothing about
  "the intelligence" needed to move anywhere for this phase.

## Testing

```powershell
python -m pytest tests/test_service_standalone.py -v
```

Covers: `pid_is_alive()` for a live process and definitely-dead PIDs,
`read_discovery_file()`'s missing/stale/live cases, the new
`schema_version`/`service_version` discovery fields, a full start→HTTP
call→graceful-stop cycle of `service/__main__.py`'s `main()` (driven via
an injectable `stop_event` rather than real OS signal delivery — signal
handlers can only be registered on the interpreter's main thread, and real
SIGTERM delivery is platform-inconsistent on Windows per the note above,
so this is the deterministic way to test the shutdown path across
platforms), and `main()`'s exit code when `start_service()` fails.

**A real cross-process port-conflict scenario was not made an automated
test**: this machine's `CoachHTTPServer` sets `allow_reuse_address = True`
(pre-existing, `server.py`, unrelated to this phase), and Windows'
`SO_REUSEADDR` semantics can let a second process bind the same loopback
port without raising — unlike POSIX, where this option only affects
`TIME_WAIT` reuse. Chasing a reliable automated reproduction of a real
same-port conflict would be testing an OS/socket-option interaction, not
this module's own logic, so the port-bind-failure path is instead tested
by mocking `start_service()`'s return value — `main()`'s reaction to a
`False` result is exactly what needed covering.

Real, manual, end-to-end verification performed this session against an
isolated fake home directory (so no real user data was touched): started
the standalone process, confirmed `service.json` with the new fields,
called `/api/v1/health` over real HTTP and got `200`, force-killed the
process, and confirmed `read_discovery_file()` correctly reported the now
stale file as `None`.

## Known limitations (of this phase, stated up front)

- **Manual start only.** Nothing yet auto-starts this process — no VS Code
  "Start Coach" command, no Windows startup entry, no installed service.
  Steps 14/15 (startup strategy, auto-start) are deliberately not part of
  Phase 4A.
- **Not packaged.** Requires this Python environment and source tree —
  there is no `ClaudeCoachService.exe` yet (Step 16, explicitly deferred).
- **Update (Phase 4C)**: the desktop app now *can* act as a pure client of
  a standalone service — see
  [DESKTOP_SERVICE_MIGRATION.md](DESKTOP_SERVICE_MIGRATION.md).
  `app.py` checks for a reachable service before starting its own, and
  connects as a client instead when one is found, rather than the two
  merely racing for the port as an incidental side effect of bind-failure
  handling (the description this bullet used to give). The embedded
  fallback itself is not removed.
- **Update (Phase 4D-A)**: the "already-running desktop does not
  retroactively give up an embedded copy" gap named right above is
  resolved — the desktop now detects and hands off to a standalone service
  that appears mid-session. See DESKTOP_SERVICE_MIGRATION.md §10. Still
  not removed: the embedded fallback itself (Phase 4D-B's job), and the
  desktop still does not auto-restart an embedded copy if it loses an
  already-connected standalone service (a deliberate choice, reasoned
  through in §10 — avoids a port race against a standalone that's merely
  restarting).
- **Update (Phase 4B)**: VS Code's own reader (`coachClient.ts`) now
  performs the same PID-liveness + `api_version` check
  `read_discovery_file()` does — this bullet is resolved, kept here only
  so the history is visible.
