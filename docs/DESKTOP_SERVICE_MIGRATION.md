# Desktop → Standalone Coach Service Migration (Phase 4C, Phase 4D-A)

**Status**: implemented, real-world verified. This document is both the
Step 1 audit (read first — it changes what "migration" turns out to mean)
and the Step 26 (Phase 4C) / Step 17 (Phase 4D-A) record of what was
actually built. See §10 for Phase 4D-A — the live handoff this document's
own §9 originally listed as a gap.

---

## 1. Audit: how the Desktop actually gets data (traced directly, not assumed)

Every page (`ui/dashboard.py`, `ui/runtime.py`, `ui/environment.py`,
`ui/settings.py`, `ui/inspector.py`, `ui/approach_advisor.py`, etc.) talks
to exactly one object: `CoachController` (`ui/controller.py`). No page
imports `database`, `runtime`, `providers`, `analyzer`, or `integration`
directly — confirmed by grep; `CoachController` is the **only** seam. This
single fact is what made this phase possible without touching page code
beyond two small additive readouts.

| Data | Current source (before Phase 4C) | Could route through HTTP? |
|---|---|---|
| Prompt history/analysis | `database/db.py` direct (sync) | Yes — `/analyze`, `/suggest`, `/approach` already exist (Phase 3) |
| Environment snapshot | `providers.ClaudeCodeEnvironmentProvider(...).scan()`, QThread-async, cached in `coach.db` | Yes — `/environment` already exists |
| Runtime status/session | `runtime.runtime_coach.RuntimeCoach.status()` — **pure SQLite read** | Already effectively shared — see §2 |
| Runtime event draining | `runtime_coach.poll_and_store()` — **writes/consumes `runtime_events/*.jsonl`** | No — this must have exactly one owner, not be "routed" anywhere |
| Hook install/uninstall | `runtime/hook_installer.py` — writes `~/.claude/settings.json` | **No** — stays local by design (Step 15's Option A logic applies equally here) |
| Skill/Agent creation | `creators/` — writes files directly | **No** — Step 15, Option A, unchanged |
| Settings | `database/db.py` get/set_setting | No — trivial local reads/writes, no benefit to HTTP |

## 2. The key finding: reads don't actually need to move

`runtime_status()` (used by Dashboard, the Sessions/Runtime page, and
Approach Advisor) is a **pure SQLite query** — `database/db.py` opens a
fresh connection per call and both the Desktop and any Coach service
(embedded or standalone) point at the **same `coach.db` file**
(`%USERPROFILE%\.claude_code_coach\coach.db`). Whichever process is
currently draining `runtime_events/*.jsonl` into that file, every other
process's read of it is equally current — SQLite's own file-level locking
already handles concurrent access safely (established fact from the
Phase 4A audit, re-confirmed here).

**This means the real risk Phase 4C's spec calls out — "races, missing
events, duplicate processing, confusing ownership" (Step 8) — is entirely
about *draining* (a destructive, consume-once operation: `event_source.py`
renames-then-deletes each `.jsonl` file as it's read), never about
*reading status*.** Rerouting every read through HTTP would have been
extra surface area solving a problem that doesn't exist for reads, at the
cost of a real one: JSON round-tripping `RuntimeStatus`/`SessionSummary`/
`RuntimeSignal` back into the exact dataclasses `ui/runtime.py` and
`integration/approach_advisor.py` already depend on, with no correctness
benefit. So Phase 4C does **not** reroute `runtime_status()`,
`environment_snapshot`, or prompt history through HTTP — those stay on
their existing, already-correct, already-fast local paths.

**What genuinely needed a fix**: only draining. See §3.

## 3. Single runtime-event-draining owner (Step 7/8/9) — the real change

### Before Phase 4C

Two independent drain paths could run at once even without any standalone
service involved:
1. `service/lifecycle.py`'s background thread (`_drain_loop`, started
   whenever `start_service()` succeeds — i.e. whenever *any* embedded or
   standalone service is running).
2. `CoachController.poll_runtime()`, called unconditionally by
   `ui/runtime.py`'s `QTimer` and `Dashboard.refresh()`.

This was already flagged as a known (harmless-by-construction, but
redundant) overlap in the Phase 4A audit
(`docs/STANDALONE_SERVICE_ARCHITECTURE.md` §5) — harmless because
`HookFileEventSource.poll()` atomically renames-then-deletes each file it
reads, so a second drainer racing the same file simply gets `OSError` and
skips it on that poll (documented in `event_source.py`), never double-
processes or loses data. Phase 4C tightens this from "harmless race" to
"exactly one drainer, by design":

```python
# claude_code_coach/ui/controller.py
def poll_runtime(self) -> int:
    if not self.runtime_enabled:
        return 0
    if self.has_reachable_backend():   # NEW — Step 8
        return 0
    return self.runtime_coach.poll_and_store()
```

`has_reachable_backend()` is a cheap, un-cached check (one small file read
+ a PID-liveness check — `service/client.py`'s `CoachBackendClient.
is_available()`) re-evaluated on **every** call, not a value fixed at
startup — so draining correctly stops the moment a service appears and
correctly resumes the moment it disappears, with no Desktop restart
required (Step 18/19). Verified directly in
`tests/test_desktop_client.py::TestRuntimeOwnership`.

### Process-level startup ownership (`app.py`)

Before starting its own embedded copy, `app.py` now checks whether a live,
compatible Coach service is already reachable:

```python
if window.controller.backend_client.is_available():
    # a standalone process, or another desktop instance, already owns
    # the backend — this process becomes a pure client
else:
    start_service()
    app.aboutToQuit.connect(stop_service)
```

This is the actual Step 7 "temporary migration behavior" decision,
implemented literally as specified: *"Is standalone service available? →
YES: connect as client, NO: retain temporary embedded fallback."* It also
means `stop_service()` (and therefore the service's teardown/cleanup) is
only ever wired to `aboutToQuit` when **this process** is the one that
started it — the Desktop closing never stops a service it doesn't own
(Scenario C, verified — see §7).

## 4. The client layer (Step 2/3)

`claude_code_coach/service/client.py` — `CoachBackendClient`, Qt-free,
stdlib-only (`urllib`, no new dependency). Reuses
`service/lifecycle.py`'s `read_discovery_file()` for discovery rather than
re-implementing it (Step 6) — the exact same three-check validation
(file/JSON shape → PID liveness → `api_version` compatibility) the VS Code
extension's `readDiscovery()` performs (Phase 4B), conceptually shared,
independently implemented per Step 3's explicit instruction ("share the
protocol definition conceptually, not implementation — do not copy
TypeScript logic literally").

`read_discovery_file()` itself gained the `api_version` check this phase
(previously only checked PID liveness) — bringing the Python-side reader
to parity with the TypeScript one, and giving both the desktop client and
any future Python caller the same `get_last_discovery_issue()` diagnostic
pattern already proven useful in Phase 4B.

`CoachBackendClient` exposes `health/status/session/environment` (GET) and
`analyze/suggest/approach` (POST) — the full existing API surface, nothing
new added, nothing renamed (Step 17). `analyze/suggest/approach` are not
wired into any Desktop page in this phase (Step 14 describes that as an
"eventually," not a Phase 4C requirement); they exist on the client now so
a later phase can wire the Prompt Inspector/Approach Advisor through the
same backend VS Code uses without a second client class.

**GUI thread safety (Step 4)**: every client call is a synchronous,
bounded-timeout (1.5s default, 10s for the three POST endpoints — matching
`coachClient.ts`'s own timeouts) loopback HTTP request, called directly
from the main thread — not routed through a `QThread`. This is deliberate,
documented in the module's own docstring: a `127.0.0.1` request either
fails in about a millisecond (nothing listening) or succeeds in well under
that, so it doesn't rise to the level the project's existing QThread
pattern (`ui/env_worker.py`, `ui/usage_worker.py`) exists for — that
pattern remains the right one for anything with real, unbounded latency
(a filesystem scan), and should be reused rather than raising this
client's timeout if a future caller needs one of the POST endpoints for
something latency-sensitive.

## 5. First migration slice (Step 5/11) — what's actually new on screen

One new, small, additive readout on **Dashboard** (in the existing RUNTIME
panel, below the existing connection-state line — nothing above it
changed) and one new section on **Settings** ("COACH SERVICE"), both
sourced from `CoachController.coach_backend_summary()`:

```json
{"reachable": true, "using_standalone": true,
 "detail": "Connected to a standalone Coach service (running independently of this app). [claude-code-coach api v1]"}
```

This is a **real** HTTP round trip (`backend_client.health()`) when a
service is reachable — genuine proof the Desktop can act as an HTTP
client of the standalone service — not a simulated or hardcoded value.
Recommendations, stats cards, habit trends, opportunities, and the
existing runtime connection-state line are **all unchanged**, per §2's
finding that they don't need to move and per Step 5/11's explicit
instruction to change only where data comes from, not the layout.

`using_standalone` distinguishes "this process's own embedded copy" from
"an external standalone service" using `service/lifecycle.py`'s existing
`is_running()` (true only if *this* process's `app.py` successfully
started the embedded copy) — no new field was added to the discovery
contract to make this distinction (consistent with Phase 4B's own finding
that no such field exists or was needed there either).

## 6. What stays local, on purpose (Step 15/16)

- **Skill/Agent creation, hook install/uninstall**: Option A, unchanged —
  these write directly to the filesystem from confirmation-gated UI
  actions, never exposed over HTTP. No architectural reason found to
  prefer Option B; the existing `server.py`/`coach_service.py` route
  table (Phase 2/3) was never touched to add these, and Phase 4C adds
  nothing there either.
- **Settings redesign**: none. Settings gained one new, small "COACH
  SERVICE" section; nothing existing was rearranged.
- **Environment scanning logic, analyzer logic, runtime interpretation
  logic**: all unchanged, all still live only in `providers/`,
  `analyzer/`, `runtime/runtime_analyzer.py` — the client (`client.py`)
  and the HTTP service (`coach_service.py`, unchanged this phase) both
  call into these, neither reimplements them.

## 7. Real-world verification performed this session

All against isolated fake home directories — the real user's
`~/.claude_code_coach` (which, incidentally, has its own live service
running independently — not touched or interfered with at any point) was
never read from or written to by any of this.

| Scenario | Result |
|---|---|
| **B** — Desktop first, nothing else running | Started its own embedded copy (`is_running(): True`), `coach_backend_summary()` correctly reports `using_standalone: False` |
| **A** — Standalone already running, Desktop starts | Did **not** start an embedded copy (`is_running(): False`), correctly reports `using_standalone: True` with a real `health()` round trip in the detail string |
| **C** — Desktop closes while standalone runs | Standalone process's PID confirmed still alive (`pid_is_alive()`) immediately after the "desktop" process exited — it was never asked to stop, because `stop_service` is only wired to `aboutToQuit` in the branch where this process started its own copy |
| **D** — Desktop reopens with service already running | Identical result to Scenario A — no special-casing needed, `has_reachable_backend()`/`read_discovery_file()` re-evaluate fresh every time |
| **E** — Service restart | Covered by `tests/test_desktop_client.py::TestReconnection` against a real running/stopped/restarted service (same client instance, no reconstruction); the stale-PID half of this was also directly verified against a real force-killed process in Phase 4A/4B and reconfirmed by this phase's `TestDiscoveryStalenessAndVersion` |

Ran using `python -m claude_code_coach.service` (Phase 4A) and a small
headless (`QT_QPA_PLATFORM=offscreen`) script that executes `app.py`'s
actual startup logic end to end, not a simulation of it.

## 8. Performance (Step 27 — measured, not claimed)

- Discovery check (`is_available()`/`has_reachable_backend()`): one small
  local file read + one Windows `OpenProcess`/`CloseHandle` pair — not
  separately timed, but the same order of magnitude as the file-stat calls
  already happening every Dashboard refresh; no observable UI delay during
  manual scenario runs above.
- `health()` round trip during Scenario A/D (real, not estimated): visibly
  completed within the same synchronous call that printed the result —
  consistent with the sub-5ms loopback latency already measured for the
  VS Code client in Phase 4B's real Node.js round trip against the same
  kind of service.
- No Desktop startup delay was observed in either scenario (B or A) — the
  discovery check and, in Scenario A, the one `health()` call both
  complete before `window.show()`'s effects would be perceptible to a
  user in a non-headless run.
- Not measured: cold-start latency on a much slower disk/machine, or
  behavior under real Windows Firewall prompts (none observed, consistent
  with every prior phase's loopback-only findings).

## 9. Known limitations (Step 25 — honest, not hidden)

- **The embedded fallback is not removed.** `app.py` still starts and
  fully owns an embedded copy whenever no other service is reachable at
  startup — this is Phase 4D's job, explicitly not attempted here.
- ~~No live migration for an already-running Desktop.~~ **Resolved in
  Phase 4D-A** — see §10. The Desktop now hands off from its embedded copy
  to a standalone service that appears later, verified with real processes
  including zero request failures observed by an external client across
  the actual handoff moment.
- **Prompt Inspector / Suggested Prompt / Approach Advisor are not wired
  through `CoachBackendClient`** in this phase (Step 14 describes this as
  a future "eventually," and Step 5 explicitly scoped this phase to one
  read-only page) — they still call `analyzer`/`integration` directly via
  `CoachController`, exactly as before. The client already supports these
  calls (§4) for whenever that migration is undertaken.
- **No automated multi-window/multi-client Windows test** beyond what
  Phase 4B already proved server-side (`tests/test_service.py`'s
  `TestMultipleProjectRequests`) — Step 20/21's "Desktop + two VS Code
  windows simultaneously" scenario was not re-run fresh this phase; the
  server-side project-isolation guarantee it depends on is unchanged and
  was not touched.

---

## 10. Phase 4D-A: seamless handoff + explicit backend modes

### Backend state machine

Three explicit states (`service/client.py`'s `BackendMode`), computed
fresh on every read by `CoachController.current_backend_mode()` — never
stored, so it can never go stale:

```
STANDALONE          — client of a service this process did not start
EMBEDDED_FALLBACK   — this process started and owns the embedded copy
UNAVAILABLE         — nothing reachable, this process's own or external
```

No `TRANSITIONING` state was added: the handoff (§ below) is a single
synchronous method that runs to completion before yielding back to the
Qt event loop, so external observers (Dashboard, Settings,
`coach_backend_summary()`) only ever see `EMBEDDED_FALLBACK` or
`STANDALONE`, never an in-between state to reason about.

### How the handoff actually works

`CoachController` owns a `QTimer` (`_backend_handoff_timer`, 15s interval
— deliberately much less frequent than the 2-3s runtime-poll intervals,
since this is a rare event) that calls `_check_for_standalone_handoff()`.
That method is a no-op unless this process currently owns the embedded
copy AND `service.json` now names a genuinely different, live process:

```
1. Not embedded right now?               -> no-op
2. Discovery file missing/invalid?       -> no-op (nothing to hand off to)
3. Discovery file's pid == our own pid?  -> no-op (that's just our own file)
4. health() against the candidate FAILS  -> no-op, log, stay embedded,
                                             retry next tick
5. health() against the candidate SUCCEEDS
        -> stop_service() (release our embedded copy)
        -> now a client of the confirmed-live external service
```

**Deliberate deviation from the spec's literal Step 3 ordering**: Step 3
lists "stop the embedded copy" (steps 1-5) *before* "verify `/api/v1/health`"
(step 8). Step 4 explicitly warns about "standalone starts then
immediately stops" — stopping a working embedded backend before
confirming its replacement is real would self-inflict exactly that outage
for no reason. This implementation checks `health()` **first** and only
stops the embedded copy once a real, responding replacement is confirmed,
so a flaky/dead-on-arrival candidate can never leave this process with
zero backend. Verified directly:
`tests/test_desktop_client.py::TestEmbeddedToStandaloneHandoff::test_stays_embedded_when_candidate_pid_is_alive_but_not_answering`
uses a real process with a live PID but nothing listening on its claimed
port, and confirms the embedded copy is never touched.

### A real bug this phase found and fixed: `stop_service()`'s discovery-file cleanup

`service.json` is one shared file, not one per process. The exact moment
an embedded copy hands off, an external service has *already* overwritten
that file with its own pid/port/token (that overwrite is *how* the
handoff check finds it in the first place). The pre-existing
`stop_service()` unconditionally unlinked `service.json` on shutdown —
which, called at exactly this moment, would have deleted the **new**
service's discovery file seconds after confirming it works, breaking
discovery for VS Code and anything else. Fixed with a small, targeted
change: `stop_service()` now only removes the file if it still names this
process's own PID (`_remove_discovery_file_if_owned_by_this_process()` in
`service/lifecycle.py`). Every existing single-process test (start then
stop in the same process) is unaffected — the file is always "owned" in
that case — and a new test
(`test_real_handoff_to_a_genuinely_running_standalone_service`) proves the
standalone's file survives our `stop_service()` call untouched.

### Runtime ownership during handoff

Exactly one drain owner at every point in time, proved with real
processes (Test E, §"Real-world verification" below): `poll_runtime()`'s
existing `has_reachable_backend()` guard (Phase 4C) already stops this
process from draining the instant the external service's discovery file
appears — *before* the handoff check's HTTP server shutdown even runs —
so there is no window where both a local drain and the standalone's own
drain loop are both active. A hook event fired immediately before the
handoff and another fired immediately after were both persisted exactly
once, with the correct prompt count and no duplicate rows.

### Fallback behavior (when EMBEDDED_FALLBACK occurs, and when it doesn't)

Unchanged from Phase 4C, restated for clarity now that it interacts with
a real handoff:

- **At Desktop startup**, if nothing is reachable, this process starts its
  own embedded copy (temporary compatibility path, Step 9/4C).
- **Once EMBEDDED_FALLBACK**, this process actively looks for a standalone
  service to hand off to (this phase's new behavior).
- **Once STANDALONE** (whether from startup or a handoff), if that service
  is later lost, this process does **not** automatically start a new
  embedded copy. It becomes `UNAVAILABLE` and waits/reconnects — see the
  reasoning below. This was already true by construction before this
  phase (there is exactly one `start_service()` call site, in `app.py`,
  run once at startup — confirmed by grep) and remains true now; no new
  code was needed to keep it true, only this explicit documentation of why
  it's the right behavior.

**Why UNAVAILABLE, not "auto-restart embedded" (Step 9's reasoning
requirement)**: pending `.jsonl` files are never lost either way
(`event_source.py`'s consume-then-delete is safe regardless of who reads
it, whenever they do). The real risk of auto-restarting an embedded copy
the moment a standalone service is lost is a **port race against a
restarting standalone**: if the standalone process is merely bouncing
(crash-and-restart, a supervisor cycling it), a Desktop that immediately
grabs the now-free port on its next tick could win the race and
permanently strand the restarting standalone behind the Desktop's own
fallback — the exact "confusing ownership" outcome this whole effort
exists to prevent, and one a human would have to notice and manually
resolve. Waiting/reconnecting (mirroring how VS Code's own Offline → Ready
cycle already works, Phase 4B) has no such failure mode: if the standalone
comes back, `has_reachable_backend()` picks it up on the very next check,
with no port ever contended.

### Explicit UI wording (Step 11/12)

`ui/widgets.py`'s new `backend_mode_label()` — one shared mapping, used by
both Dashboard and Settings so the two pages can never describe the same
state two different ways:

| `BackendMode` | Label shown |
|---|---|
| `STANDALONE` | "Standalone" |
| `EMBEDDED_FALLBACK` | "Compatibility fallback" |
| `UNAVAILABLE` | "Unavailable" |

No raw enum text, no new architecture page — both pages gained exactly one
additional line each.

### Real-world verification performed this session (Tests A-E)

All against isolated fake home directories with `port=0` (ephemeral) for
every test-started service — **not** the real `DEFAULT_PORT` (47823),
because this development machine has a real, independently-running Coach
service on that exact port that predates this entire session (confirmed
separately, never touched). An early manual verification run that
mistakenly used the default port produced confusing, intermittent 401s —
a direct, real demonstration of the Windows `SO_REUSEADDR` hazard already
documented in `STANDALONE_SERVICE.md`'s testing notes, and a good reminder
of why every automated test in this repository already isolates its own
port.

| Test | Result |
|---|---|
| A — Standalone first | Desktop connects as a client, never starts an embedded copy |
| B — Desktop first | Desktop starts its embedded copy (`EMBEDDED_FALLBACK`) |
| C — Live handoff | Real subprocess handoff: embedded copy genuinely stopped, `service.json` correctly ends up naming the standalone's pid, `current_backend_mode()` becomes `STANDALONE` |
| D — VS Code during handoff | A real HTTP poller (re-reading `service.json` fresh every 0.3s, exactly like `coachClient.ts`) recorded **48/48 successful requests, zero failures**, across the entire handoff — genuinely seamless from an external client's point of view |
| E — Runtime events during handoff | One hook event fired immediately before the handoff, another immediately after: both persisted exactly once (`prompts: 2`, exactly 3 event rows — 1 `SessionStart` + 2 `UserPromptSubmit`), no loss, no duplication |

**A real, if minor, operational finding surfaced while building the Test
D/E harness** (not a Phase 4D-A code defect): launching the standalone
service as a subprocess with `stdout=subprocess.PIPE`/`stderr=subprocess.PIPE`
and never draining those pipes let the OS pipe buffer fill under the
test's heavy polling volume (each request logs one line via
`server.py`'s `log_message()`), which blocked the child process's next
log write and stalled its request handling entirely — reproduced
consistently, fixed by redirecting to `DEVNULL` once nothing needs to
inspect that output. Worth documenting for anyone building a supervisor/
launcher around `python -m claude_code_coach.service` (Step 16+): drain or
discard its output, don't leave an unread pipe attached under load.

### Recommendation: is the embedded backend now safe to remove?

**Not yet — one more stabilization phase, as the spec's own Step 18/STOP
condition anticipates.** What Phase 4D-A adds is confidence that the
*mechanism* works correctly under real conditions (verified above); what
it does not yet have is real elapsed usage time with the mechanism active
across ordinary, non-scripted Desktop sessions. Recommended before
Phase 4D-B (remove embedded service completely):

1. Real usage across a normal work session or two, with the handoff path
   actually exercised at least once outside of a test harness.
2. A decision on the one remaining documented edge case: an
   already-`STANDALONE` Desktop that loses the standalone and later has
   *another* one appear — this now works via the same
   `has_reachable_backend()` reconnect path (never needed an embedded
   copy in the first place in that case), but was not separately exercised
   as its own named scenario this phase.
3. Confirmation that the 15s handoff-check interval is an acceptable
   detection latency in practice (chosen deliberately conservative per
   Step 6's "do not poll aggressively"; easy to tune later if real usage
   shows it should be shorter).
