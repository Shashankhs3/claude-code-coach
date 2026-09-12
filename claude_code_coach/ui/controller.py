"""Thin app controller shared by every page.

Centralizes database access and analysis so pages don't talk to sqlite or
the analyzer package directly, and provides a single refresh_all() so that
saving a prompt or clearing the database keeps every page in sync.

V3.1 adds real environment discovery: a ClaudeCodeEnvironmentProvider is
scanned on a background QThread (never blocking the UI) and the resulting
snapshot is both cached in memory and persisted as metadata-only rows so it
survives an app restart until the next "Scan Again".
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer

from claude_code_coach import database as db
from claude_code_coach.analyzer import AnalysisResult, analyze_prompt
from claude_code_coach.analyzer.prompt_rewriter import PromptSuggestion, suggest_prompt
from claude_code_coach.creators import (
    AgentDraft,
    SkillDraft,
    agent_path as agent_file_path,
    render_agent_md,
    render_skill_md,
    save_agent,
    save_skill,
    skill_path as skill_file_path,
    validate_agent_draft,
    validate_skill_draft,
)
from claude_code_coach.integration import ApproachReport, recommend_approach
from claude_code_coach.providers import (
    AgentInfo,
    ClaudeCodeEnvironmentProvider,
    ClaudeMdInfo,
    EnvironmentSnapshot,
    McpServerInfo,
    NullSessionProvider,
    SkillInfo,
    Source,
)
from claude_code_coach.runtime.event_source import HookFileEventSource, NullRuntimeEventSource
from claude_code_coach.runtime.runtime_coach import RuntimeCoach
from claude_code_coach.service import BackendMode, CoachBackendClient, ServiceUnavailableError
from claude_code_coach.service import lifecycle as _service_lifecycle
from claude_code_coach.service.lifecycle import is_running as _embedded_service_owned_here

from .env_worker import EnvironmentScanWorker
from .usage_worker import UsageScanWorker

logger = logging.getLogger("claude_code_coach.app")
# Phase 4D-A Step 6: how often, while running the temporary embedded
# fallback, to check whether an external standalone service has appeared
# to hand off to. Deliberately much less frequent than the 2-3s runtime-
# event drain/poll intervals elsewhere — this is a rare event, not one
# that needs near-real-time detection the way a new hook event does.
BACKEND_HANDOFF_CHECK_INTERVAL_MS = 15_000


def _source(value: str | None) -> Source:
    try:
        return Source(value)
    except ValueError:
        return Source.UNKNOWN


def _snapshot_from_cached_row(row: dict) -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        scanned_at=row.get("scanned_at", ""),
        project_root=row.get("project_root"),
        claude_md=[
            ClaudeMdInfo(
                path=d["path"], scope=_source(d["scope"]), size_bytes=d["size_bytes"],
                modified=d["modified"], preview=d["preview"],
            ) for d in row.get("claude_md", [])
        ],
        skills=[
            SkillInfo(
                name=s["name"], path=s["path"], description=s["description"],
                source=_source(s["source"]), modified=s["modified"],
            ) for s in row.get("skills", [])
        ],
        agents=[
            AgentInfo(
                name=a["name"], path=a["path"], description=a["description"],
                source=_source(a["source"]), modified=a["modified"],
            ) for a in row.get("agents", [])
        ],
        mcp_servers=[
            McpServerInfo(
                name=m["name"], server_type=m["server_type"], source=_source(m["source"]),
                config_path=m["config_path"],
                enabled=None if m["enabled"] is None else bool(m["enabled"]),
            ) for m in row.get("mcp_servers", [])
        ],
        errors=row.get("errors", []),
    )


class CoachController(QObject):
    """A QObject (not just a plain class) specifically so
    scan_environment_async()'s worker-thread signals can be connected to a
    receiver with real main-thread affinity — see that method's docstring.
    Nothing else about this class depends on being a QObject; every other
    method is plain Python exactly as before.
    """

    def __init__(self):
        super().__init__()
        self.session = NullSessionProvider()

        project_root = db.get_setting("project_root")
        self.environment = ClaudeCodeEnvironmentProvider(
            project_root=project_root or None, user_home=Path.home()
        )

        cached = db.fetch_environment_snapshot()
        self.environment_snapshot: EnvironmentSnapshot | None = (
            _snapshot_from_cached_row(cached) if cached else None
        )
        self.scan_on_startup = db.get_setting("scan_on_startup", "0") == "1"

        self.runtime_enabled = db.get_setting("runtime_enabled", "1") == "1"
        self.runtime_coach = RuntimeCoach(
            source=self._build_runtime_source() if self.runtime_enabled else NullRuntimeEventSource()
        )

        # Phase 4C: this process's HTTP client for the Coach service —
        # desktop-embedded or standalone, indistinguishable at the wire
        # level (see service/client.py). runtime_status()/environment
        # scanning below still read/write the shared coach.db and
        # filesystem directly — they do NOT need to go through HTTP to see
        # a standalone service's writes, since both processes share the
        # same database file (see docs/DESKTOP_SERVICE_MIGRATION.md).
        # What DOES need this client: poll_runtime()'s single-owner guard
        # below, and coach_backend_summary() for the Dashboard/Settings
        # readout (Step 5's "first migration slice").
        self.backend_client = CoachBackendClient()

        # Phase 4D-A, Step 6: while this process owns the temporary
        # embedded fallback, periodically check whether an external
        # standalone service has appeared to hand off to — see
        # _check_for_standalone_handoff()'s own docstring for exactly how.
        # QTimer(self) created only after super().__init__() above has
        # fully run — the same ordering rule ui/runtime.py's and
        # ui/inspector.py's own QTimers already follow, for the same
        # reason (spec section 33; see those files' comments).
        self._backend_handoff_timer = QTimer(self)
        self._backend_handoff_timer.timeout.connect(self._check_for_standalone_handoff)
        self._backend_handoff_timer.start(BACKEND_HANDOFF_CHECK_INTERVAL_MS)

        self.workshop_mode = db.get_setting("workshop_mode", "0") == "1"

        self._pages: list = []
        self._navigation_callback = None
        self._scan_thread: QThread | None = None
        self._scan_worker: EnvironmentScanWorker | None = None
        self._scan_on_done = None
        self._scan_on_error = None

        self._usage_scan_thread: QThread | None = None
        self._usage_scan_worker: UsageScanWorker | None = None
        self._usage_scan_on_done = None
        self._usage_scan_on_error = None
        # Cache-first, same pattern as environment_snapshot above: a scan
        # only ever runs when explicitly asked for (first visit to the
        # Usage page, or its Rescan button) — never unconditionally at
        # every app startup, since ALL pages are constructed eagerly here
        # in __init__ regardless of whether the user ever visits them.
        self.usage_summary = None

    # -- page registry --------------------------------------------------
    def register(self, page) -> None:
        self._pages.append(page)

    def refresh_all(self) -> None:
        for page in self._pages:
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                refresh()

    # -- cross-page navigation (e.g. "Create Skill" from a candidate card) -------
    def set_navigation_callback(self, callback) -> None:
        self._navigation_callback = callback

    def navigate_to(self, label: str) -> None:
        if getattr(self, "_navigation_callback", None):
            self._navigation_callback(label)

    def start_skill_draft_from_candidate(self, candidate: dict) -> None:
        examples = "\n".join(f"- {e}" for e in candidate.get("examples", []))
        self.save_skill_draft_progress({
            "name": "", "purpose": candidate.get("reason", ""),
            "when_to_use": f"When performing a workflow similar to: {candidate.get('name', '')}",
            "workflow": examples, "rules": "", "constraints": "", "avoid": "",
            "expected_output": "", "examples": examples,
        })
        self.navigate_to("Skill Creator")

    def start_agent_draft_from_candidate(self, candidate: dict) -> None:
        examples = "\n".join(f"- {e}" for e in candidate.get("examples", []))
        self.save_agent_draft_progress({
            "name": "", "purpose": candidate.get("reason", ""),
            "role": f"Delegated investigator for: {candidate.get('name', '')}",
            "responsibilities": examples,
            "investigation_instructions": "", "allowed_actions": "", "restrictions": "",
            "may_modify_source": False, "expected_output": "",
            "verification_requirements": "",
        })
        self.navigate_to("Agent Creator")

    # -- analysis ---------------------------------------------------------
    def analyze(self, prompt: str) -> AnalysisResult:
        return analyze_prompt(prompt)

    def save(self, result: AnalysisResult) -> int:
        return db.insert_prompt(result.to_row())

    def suggest_prompt(self, prompt: str, analysis: AnalysisResult | None = None) -> PromptSuggestion:
        return suggest_prompt(prompt, analysis)

    def recommend_approach(self, prompt: str, analysis: AnalysisResult | None = None) -> ApproachReport:
        analysis = analysis or self.analyze(prompt)
        runtime_status = self.runtime_status() if self.runtime_enabled else None
        return recommend_approach(prompt, analysis, self.environment_snapshot, runtime_status)

    def top_recommendations(self, limit: int = 3):
        """Dashboard Feature 12: at most `limit` high-value recommendations,
        combining the live runtime session (if any) with the most recently
        analyzed prompt — never a giant list of every possible signal.
        """
        recs = []
        if self.runtime_enabled:
            status = self.runtime_status()
            for sig in status.signals:
                icon = {"broad_exploration": "⚠", "context_growth": "🧠",
                        "agent_delegation_opportunity": "🤖", "skill_underused": "🔧",
                        "repeated_workflow_no_skill": "🔧", "context_noisy": "⚠",
                        "verification_missing": "⚠"}.get(sig.kind, "•")
                recs.append((sig.level, f"{icon} {sig.message}"))

        recent = self.history(limit=1)
        if recent:
            report = self.recommend_approach(recent[0]["prompt"])
            for rec in report.recommendations:
                if rec.kind == "normal_session":
                    continue
                recs.append((rec.level, f"{rec.icon} {rec.message}"))

        order = {"high": 0, "medium": 1, "low": 2}
        recs.sort(key=lambda r: order.get(r[0], 3))
        seen = set()
        out = []
        for _level, msg in recs:
            if msg not in seen:
                seen.add(msg)
                out.append(msg)
            if len(out) >= limit:
                break
        return out

    # -- history ------------------------------------------------------------
    def history(self, limit: int | None = None) -> list[dict]:
        return db.fetch_all_prompts(limit=limit)

    def get(self, row_id: int) -> dict | None:
        return db.fetch_prompt(row_id)

    def count(self) -> int:
        return db.count_prompts()

    # -- environment (V3.1) --------------------------------------------------
    def set_project_root(self, path: str | None) -> None:
        db.set_setting("project_root", path or "")
        self.environment = ClaudeCodeEnvironmentProvider(
            project_root=path or None, user_home=Path.home()
        )

    def set_scan_on_startup(self, enabled: bool) -> None:
        self.scan_on_startup = enabled
        db.set_setting("scan_on_startup", "1" if enabled else "0")

    def scan_environment_sync(self) -> EnvironmentSnapshot:
        """Blocking scan — used by tests and as the worker's own call target."""
        snapshot = self.environment.scan()
        self.environment_snapshot = snapshot
        db.save_environment_snapshot(snapshot)
        return snapshot

    def scan_environment_async(self, on_done=None, on_error=None) -> bool:
        """Scan on a background thread so the UI stays responsive.

        Returns False (and does nothing) if a scan is already running.

        worker.finished/failed are emitted on the background thread and
        are connected to real bound methods of `self` (_on_scan_finished/
        _on_scan_failed) rather than to plain local closures. That's not
        cosmetic: CoachController is a QObject that is never moved off the
        main thread, so Qt's AutoConnection can see the emitter (worker,
        on the background thread) and receiver (self, on the main thread)
        have different thread affinities and correctly delivers the call
        via a real queued connection, processed on the main thread's event
        loop. A plain Python closure has no thread affinity of its own for
        Qt to compare against, so a connection to one resolves to Direct
        and runs ON the worker thread instead — which is what used to
        happen here, and is what caused every widget update inside
        refresh_all() (reached via on_done) to be an illegal cross-thread
        QObject operation: the real cause of the repeated
        "QObject::setParent: Cannot set parent, new parent is in a
        different thread" warnings, "QThread: Destroyed while thread ''
        is still running", and an associated native crash risk — not just
        a cosmetic warning. (Forcing Qt.QueuedConnection onto the old
        plain-closure connection was tried and made things worse: with no
        QObject receiver to attach the queued event to, delivery never
        happened at all and the scan appeared to hang forever.)
        """
        if self._scan_thread is not None and self._scan_thread.isRunning():
            return False

        thread = QThread()
        worker = EnvironmentScanWorker(self.environment)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        # Only one scan can be in flight at a time (guarded by the early
        # return above), so stashing this call's callbacks on self is safe
        # for _on_scan_finished/_on_scan_failed to pick up later.
        self._scan_on_done = on_done
        self._scan_on_error = on_error

        worker.finished.connect(self._on_scan_finished)
        worker.failed.connect(self._on_scan_failed)
        # thread.finished is the real Qt lifecycle signal — emitted right as
        # the underlying OS thread is actually about to stop, unlike
        # worker.finished/failed above (which only mean "the scan produced
        # a result"; thread.quit() has been asked for but the thread may
        # not have stopped yet). _on_scan_thread_finished is connected
        # FIRST so it runs before thread.deleteLater() below, on the same
        # queued delivery to the main thread — see that method's docstring
        # for why the ordering here matters.
        thread.finished.connect(self._on_scan_thread_finished)
        thread.finished.connect(thread.deleteLater)

        self._scan_thread = thread
        self._scan_worker = worker
        thread.start()
        return True

    def _on_scan_finished(self, snapshot: EnvironmentSnapshot) -> None:
        self.environment_snapshot = snapshot
        try:
            db.save_environment_snapshot(snapshot)
        except Exception:  # noqa: BLE001 - persistence failure shouldn't hide the scan result
            pass
        if self._scan_thread is not None:
            self._scan_thread.quit()
        on_done, self._scan_on_done = self._scan_on_done, None
        if on_done:
            on_done(snapshot)

    def _on_scan_thread_finished(self) -> None:
        """Only safe point to drop the last Python reference to the scan's
        QThread. Clearing _scan_thread earlier — e.g. right inside
        _on_scan_finished, as this code used to — drops the reference
        while the OS thread `thread.quit()` just asked to stop may still
        actually be finishing, which is exactly what "QThread: Destroyed
        while thread '' is still running" (and, separately, a stale
        C++-side reference — "libshiboken: Internal C++ object already
        deleted" from a later is_scanning() call) came from. Waiting for
        the real thread.finished signal guarantees the underlying thread
        has actually stopped before anything drops or observes this
        reference again.
        """
        self._scan_thread = None
        self._scan_worker = None

    def _on_scan_failed(self, message: str) -> None:
        if self._scan_thread is not None:
            self._scan_thread.quit()
        on_error, self._scan_on_error = self._scan_on_error, None
        if on_error:
            on_error(message)

    def is_scanning(self) -> bool:
        return self._scan_thread is not None and self._scan_thread.isRunning()

    # -- usage (token/cost) scan ------------------------------------------------
    # Mirrors scan_environment_async() above exactly, including the same
    # QObject-bound-method connection (so worker.finished/failed, emitted on
    # the background thread, are correctly queued to the main thread by Qt's
    # AutoConnection) and the same "only drop the QThread reference once the
    # real thread.finished fires" lifecycle — both were hard-won fixes for a
    # real bug (see that method's docstring); reusing the identical pattern
    # here rather than inventing a slightly different one is deliberate.
    def scan_usage_async(self, on_done=None, on_error=None) -> bool:
        if self._usage_scan_thread is not None and self._usage_scan_thread.isRunning():
            return False

        thread = QThread()
        worker = UsageScanWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        self._usage_scan_on_done = on_done
        self._usage_scan_on_error = on_error

        worker.finished.connect(self._on_usage_scan_finished)
        worker.failed.connect(self._on_usage_scan_failed)
        thread.finished.connect(self._on_usage_scan_thread_finished)
        thread.finished.connect(thread.deleteLater)

        self._usage_scan_thread = thread
        self._usage_scan_worker = worker
        thread.start()
        return True

    def _on_usage_scan_finished(self, summary) -> None:
        self.usage_summary = summary
        if self._usage_scan_thread is not None:
            self._usage_scan_thread.quit()
        on_done, self._usage_scan_on_done = self._usage_scan_on_done, None
        if on_done:
            on_done(summary)

    def _on_usage_scan_failed(self, message: str) -> None:
        if self._usage_scan_thread is not None:
            self._usage_scan_thread.quit()
        on_error, self._usage_scan_on_error = self._usage_scan_on_error, None
        if on_error:
            on_error(message)

    def _on_usage_scan_thread_finished(self) -> None:
        self._usage_scan_thread = None
        self._usage_scan_worker = None

    def is_usage_scanning(self) -> bool:
        return self._usage_scan_thread is not None and self._usage_scan_thread.isRunning()

    def shutdown(self) -> None:
        """Called from app.py's aboutToQuit. Neither scan_environment_async
        nor scan_usage_async previously had any way to know the application
        itself was closing — if the user closed the app while either scan
        was still in flight (the usage scan in particular, since Usage's
        page constructor kicks one off unconditionally at startup, unlike
        the environment scan which is gated behind scan_on_startup), Qt's
        own application teardown could destroy a QThread object while its
        underlying OS thread was still actually running: "QThread:
        Destroyed while thread '' is still running" — a real, if racy,
        gap the thread.finished-gated reference-clearing above doesn't
        close by itself, since that only protects against dropping this
        controller's OWN reference early, not against the interpreter
        tearing everything down while a thread is genuinely still active.
        A bounded wait() here means a scan in progress gets a real chance
        to finish (or is told to quit and given a moment to actually stop)
        before anything is destroyed.
        """
        for thread in (self._scan_thread, self._usage_scan_thread):
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait(2000)
        # Phase 4D-A: no correctness requirement (a stopped event loop
        # simply stops delivering timeout() ticks either way), but stopping
        # explicitly avoids a handoff check firing during the brief window
        # between aboutToQuit and process exit.
        self._backend_handoff_timer.stop()

    # -- runtime (V4) --------------------------------------------------------
    def _build_runtime_source(self) -> HookFileEventSource:
        # Derive from DB_PATH.parent (not the module-level APP_DIR constant)
        # so that tests overriding db.DB_PATH correctly isolate this too —
        # APP_DIR is computed once at import time and won't reflect a later
        # DB_PATH override.
        return HookFileEventSource(db.DB_PATH.parent / "runtime_events")

    def poll_runtime(self) -> int:
        """Drains runtime_events/*.jsonl into coach.db — but ONLY when no
        other Coach service is already doing that job (Phase 4C Step 7/8:
        "there must be ONE authoritative event-draining owner"). Checked
        fresh on every call (a single small file read + PID check — see
        service/client.py's is_available()) rather than once at startup,
        so this correctly stops draining the moment a standalone service
        appears, and correctly resumes if that service later disappears —
        no restart required (Step 18/19).

        Reading is unaffected either way: runtime_status() below always
        reads directly from coach.db, which is safe and current regardless
        of *which* process most recently drained into it, since every
        process shares the same database file. Only the drain/write side
        needs a single owner; reads never did.

        Note this also closes a narrower, pre-existing redundancy from
        Phase 2/3 (see docs/STANDALONE_SERVICE_ARCHITECTURE.md §5): even
        this process's OWN embedded service already runs its own
        background drain thread (service/lifecycle.py's _drain_loop) once
        start_service() succeeds, independent of this method. Before Phase
        4C, poll_runtime() drained a second time on top of that
        unconditionally — harmless (draining is idempotent by
        construction) but redundant. Gating on has_reachable_backend()
        (true once EITHER this process's own embedded copy or an external
        standalone one is up) removes that redundancy too, not just the
        cross-process standalone case.
        """
        if not self.runtime_enabled:
            return 0
        if self.has_reachable_backend():
            return 0
        return self.runtime_coach.poll_and_store()

    def has_reachable_backend(self) -> bool:
        """True if a live, compatible Coach service — this process's own
        embedded copy or an external standalone one, indistinguishable
        from here — is reachable right now, meaning SOME process already
        owns draining runtime_events/*.jsonl and this one must not also do
        it (see poll_runtime()). Re-checked on every call, never cached,
        so a service appearing/disappearing while the Desktop is open is
        picked up on the very next check (Step 18: reconnect without
        restarting). Use current_backend_mode() when you specifically need
        to know whether the reachable service is an EXTERNAL one rather
        than this process's own."""
        return self.backend_client.is_available()

    def current_backend_mode(self) -> BackendMode:
        """Phase 4D-A, Step 2: the one place that turns "is my own embedded
        copy running" + "is anything reachable" into the three explicit
        states the rest of this class and the UI reason about. Computed
        fresh every call — never stored — for the same reconnect-without-
        restarting reason has_reachable_backend() is. STANDALONE also
        covers "connected to another desktop instance's embedded copy";
        that distinction was never made anywhere in this codebase and
        Phase 4D-A does not start making it now (Step 18: no new
        architecture, only ownership/fallback behavior).
        """
        if _embedded_service_owned_here():
            return BackendMode.EMBEDDED_FALLBACK
        if self.backend_client.is_available():
            return BackendMode.STANDALONE
        return BackendMode.UNAVAILABLE

    def coach_backend_summary(self) -> dict:
        """Phase 4C Step 5/16, extended Phase 4D-A: the one additive
        readout proving the Desktop can consume the standalone service as
        a real HTTP client — shown on the Dashboard and Settings,
        everything else on both pages unchanged. Returns
        {reachable, using_standalone, mode, detail} — never raises; a
        service that's merely slow to answer health() still reports
        reachable=True (discovery already confirmed a live, compatible
        service) with a shorter detail string rather than failing the
        whole summary over one slow health check.
        """
        mode = self.current_backend_mode()
        if mode is BackendMode.UNAVAILABLE:
            return {
                "reachable": False,
                "using_standalone": False,
                "mode": mode,
                "detail": self.backend_client.discovery_issue() or "No Coach service is currently running.",
            }
        detail = (
            "Connected to this app's own embedded Coach service (temporary compatibility fallback)."
            if mode is BackendMode.EMBEDDED_FALLBACK else
            "Connected to a standalone Coach service (running independently of this app)."
        )
        try:
            health = self.backend_client.health()
            detail += f" [{health.get('service', 'coach')} api {health.get('api_version', '?')}]"
        except Exception:  # noqa: BLE001 - a slow/flaky health call must not break this summary
            pass
        return {
            "reachable": True,
            "using_standalone": mode is BackendMode.STANDALONE,
            "mode": mode,
            "detail": detail,
        }

    def _check_for_standalone_handoff(self) -> None:
        """Phase 4D-A, Step 3/4/8: called every
        BACKEND_HANDOFF_CHECK_INTERVAL_MS by self._backend_handoff_timer.
        A no-op unless this process currently owns the embedded fallback
        AND service.json now names a *different*, live, compatible, and
        (crucially) actually-responding process.

        Ordering is deliberately NOT the literal Step 3 sequence (which
        stops the embedded copy before verifying the candidate's health):
        Step 4 explicitly warns about "standalone starts then immediately
        stops," and stopping our own working backend before confirming the
        replacement is real would self-inflict exactly that outage for no
        reason. This checks health() FIRST and only stops our own copy
        once a real, live, responding replacement is confirmed — never
        leaving this process with zero backend as a result of a handoff
        attempt. If the candidate turns out to be unreachable, this
        process simply stays EMBEDDED_FALLBACK and tries again next tick.
        """
        if not _embedded_service_owned_here():
            return  # not embedded right now — nothing to hand off from

        discovery = _service_lifecycle.read_discovery_file()
        if discovery is None:
            return  # nothing external and valid right now
        if discovery.get("pid") == os.getpid():
            return  # that's just our own file — no external service exists yet

        candidate_pid = discovery.get("pid")
        try:
            self.backend_client.health()
        except ServiceUnavailableError:
            # Discovery looked valid a moment ago but the candidate isn't
            # actually answering right now (Step 4's exact race) — stay
            # embedded and re-check on the next tick rather than guessing.
            logger.info(
                "Candidate standalone Coach service (pid %s) found but did not "
                "respond to health check — staying on embedded fallback.", candidate_pid,
            )
            return

        logger.info(
            "Standalone Coach service detected (pid %s) and responded to health "
            "check — handing off from this app's embedded copy.", candidate_pid,
        )
        _service_lifecycle.stop_service()
        logger.info(
            "Embedded Coach service stopped; this app is now a client of the "
            "standalone service (pid %s).", candidate_pid,
        )

    def runtime_status(self):
        return self.runtime_coach.status(environment_snapshot=self.environment_snapshot)

    # -- shared coaching pause (Phase 4E, docs/SHARED_COACH_STATE.md §5) --------
    def coaching_paused(self) -> bool:
        """Cheap direct read (one `db.get_setting` call) for callers — e.g.
        the Settings checkbox — that only need the flag, not a full
        runtime_status() computation. `RuntimeStatus.paused` (from
        runtime_status()) reads the exact same setting."""
        from claude_code_coach.runtime.runtime_coach import is_coaching_paused
        return is_coaching_paused()

    def set_coaching_paused(self, enabled: bool) -> None:
        """Writes the same `coaching_paused` row in coach.db a standalone
        service's `/api/v1/pause` handler writes — shared automatically the
        moment this process and a standalone service point at the same
        database file (no new cross-process protocol needed). Also nudges
        the existing vscode_signal.txt mechanism so a co-located standalone
        service's VS Code windows refresh promptly, matching what the HTTP
        endpoint does — best-effort, since this Desktop process may not be
        the one running that service's drain loop at all."""
        from claude_code_coach.runtime.runtime_coach import set_coaching_paused as _set_paused
        _set_paused(enabled)
        try:
            _service_lifecycle.notify_state_changed("pause_changed")
        except Exception:  # noqa: BLE001 - the setting write above already succeeded
            pass

    def default_hooks_settings_path(self) -> Path:
        root = self.environment.project_root
        if root:
            return Path(root) / ".claude" / "settings.json"
        return Path.home() / ".claude" / "settings.json"

    def install_runtime_hooks(self, settings_path) -> dict:
        return self.runtime_coach.install(str(settings_path))

    def uninstall_runtime_hooks(self, settings_path) -> dict:
        return self.runtime_coach.uninstall(str(settings_path))

    def set_runtime_enabled(self, enabled: bool) -> None:
        self.runtime_enabled = enabled
        db.set_setting("runtime_enabled", "1" if enabled else "0")
        self.runtime_coach.source = (
            self._build_runtime_source() if enabled else NullRuntimeEventSource()
        )

    def set_runtime_collect_content(self, enabled: bool) -> None:
        db.set_setting("runtime_collect_content", "1" if enabled else "0")

    def runtime_collect_content(self) -> bool:
        return db.get_setting("runtime_collect_content", "0") == "1"

    def set_runtime_retention_days(self, days: int | None) -> None:
        db.set_setting("runtime_retention_days", str(days) if days else "")

    def runtime_retention_days(self) -> int | None:
        value = db.get_setting("runtime_retention_days", "")
        return int(value) if value else None

    def apply_runtime_retention(self) -> int:
        days = self.runtime_retention_days()
        if not days:
            return 0
        return self.runtime_coach.purge_older_than(days)

    # -- workshop mode (V5) ---------------------------------------------------
    def set_workshop_mode(self, enabled: bool) -> None:
        self.workshop_mode = enabled
        db.set_setting("workshop_mode", "1" if enabled else "0")

    # -- Skill/Agent Creator (V5) -----------------------------------------------
    def _project_root_or_raise(self) -> Path:
        root = self.environment.project_root
        if not root:
            raise ValueError(
                "No project folder selected. Choose one on the Environment or "
                "Settings page first."
            )
        return Path(root)

    def load_skill_draft(self) -> dict | None:
        return db.get_skill_draft()

    def save_skill_draft_progress(self, draft: dict) -> None:
        db.save_skill_draft(draft)

    def validate_skill(self, draft: SkillDraft):
        root = self.environment.project_root
        return validate_skill_draft(draft, root)

    def preview_skill(self, draft: SkillDraft) -> str:
        return render_skill_md(draft)

    def skill_already_exists(self, name: str) -> bool:
        root = self.environment.project_root
        return bool(root) and skill_file_path(root, name).exists()

    def save_skill_file(self, draft: SkillDraft, *, overwrite: bool = False) -> dict:
        root = self._project_root_or_raise()
        result = save_skill(root, draft, overwrite=overwrite)
        db.clear_skill_draft()
        self.scan_environment_async(on_done=lambda snap: self.refresh_all())
        return result

    def load_agent_draft(self) -> dict | None:
        return db.get_agent_draft()

    def save_agent_draft_progress(self, draft: dict) -> None:
        db.save_agent_draft(draft)

    def validate_agent(self, draft: AgentDraft):
        root = self.environment.project_root
        return validate_agent_draft(draft, root)

    def preview_agent(self, draft: AgentDraft) -> str:
        return render_agent_md(draft)

    def agent_already_exists(self, name: str) -> bool:
        root = self.environment.project_root
        return bool(root) and agent_file_path(root, name).exists()

    def save_agent_file(self, draft: AgentDraft, *, overwrite: bool = False) -> dict:
        root = self._project_root_or_raise()
        result = save_agent(root, draft, overwrite=overwrite)
        db.clear_agent_draft()
        self.scan_environment_async(on_done=lambda snap: self.refresh_all())
        return result

    # -- maintenance --------------------------------------------------------
    def clear_all(self) -> None:
        db.clear_all()
        self.environment_snapshot = None
        self.refresh_all()

    def db_info(self) -> dict:
        return db.db_info()

    def export_json(self, path) -> int:
        return db.export_json(path)

    def import_json(self, path) -> int:
        count = db.import_json(path)
        self.refresh_all()
        return count
