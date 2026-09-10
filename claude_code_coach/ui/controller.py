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

from pathlib import Path

from PySide6.QtCore import QThread

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

from .env_worker import EnvironmentScanWorker


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


class CoachController:
    def __init__(self):
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

        self.workshop_mode = db.get_setting("workshop_mode", "0") == "1"

        self._pages: list = []
        self._navigation_callback = None
        self._scan_thread: QThread | None = None
        self._scan_worker: EnvironmentScanWorker | None = None

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
        """
        if self._scan_thread is not None and self._scan_thread.isRunning():
            return False

        thread = QThread()
        worker = EnvironmentScanWorker(self.environment)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        def _handle_done(snapshot: EnvironmentSnapshot) -> None:
            self.environment_snapshot = snapshot
            try:
                db.save_environment_snapshot(snapshot)
            except Exception:  # noqa: BLE001 - persistence failure shouldn't hide the scan result
                pass
            thread.quit()
            if on_done:
                on_done(snapshot)

        def _handle_error(message: str) -> None:
            thread.quit()
            if on_error:
                on_error(message)

        worker.finished.connect(_handle_done)
        worker.failed.connect(_handle_error)
        thread.finished.connect(thread.deleteLater)

        self._scan_thread = thread
        self._scan_worker = worker
        thread.start()
        return True

    def is_scanning(self) -> bool:
        return self._scan_thread is not None and self._scan_thread.isRunning()

    # -- runtime (V4) --------------------------------------------------------
    def _build_runtime_source(self) -> HookFileEventSource:
        # Derive from DB_PATH.parent (not the module-level APP_DIR constant)
        # so that tests overriding db.DB_PATH correctly isolate this too —
        # APP_DIR is computed once at import time and won't reflect a later
        # DB_PATH override.
        return HookFileEventSource(db.DB_PATH.parent / "runtime_events")

    def poll_runtime(self) -> int:
        if not self.runtime_enabled:
            return 0
        return self.runtime_coach.poll_and_store()

    def runtime_status(self):
        return self.runtime_coach.status(environment_snapshot=self.environment_snapshot)

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
