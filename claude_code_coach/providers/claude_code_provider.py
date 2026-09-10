"""Real, read-only Claude Code environment scanner.

Locations scanned (spec section 2 — inspected against an actual Claude Code
installation before writing this; see README "Environment scanning" for the
notes): both roots are configurable, never hard-coded to one machine.

Project-scoped (under a configurable ``project_root``):
    <project_root>/CLAUDE.md                     - project memory
    <project_root>/.claude/skills/*/SKILL.md      - project Skills
    <project_root>/.claude/agents/*.md            - project Agents
    <project_root>/.mcp.json                      - shareable project MCP config
    parent directories of project_root up to the filesystem root or the
    user's home, each checked for a CLAUDE.md (Claude Code reads these too)

User-scoped (under a configurable ``user_home``, default ``Path.home()``):
    <user_home>/.claude/CLAUDE.md                 - global user memory
    <user_home>/.claude/skills/*/SKILL.md         - user Skills
    <user_home>/.claude/agents/*.md               - user Agents
    <user_home>/.claude/settings.json             - may declare mcpServers
    <user_home>/.claude.json  -> projects[<project_root>].mcpServers        - the
        real, currently-observed location for project-scoped MCP servers
        registered via `claude mcp add` (only the matching project's entry
        is ever read — the rest of this large, account-scoped file is never
        parsed or stored)

This scanner never executes anything it finds, never connects to an MCP
server, and never writes to any of these locations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .interfaces import EnvironmentProvider
from .models import AgentInfo, ClaudeMdInfo, EnvironmentSnapshot, McpServerInfo, SkillInfo, Source
from .redaction import redact_secrets

PREVIEW_CHARS = 400
MAX_PARENT_WALK = 8


def _normalize_path(p: str) -> str:
    return str(Path(p)).replace("\\", "/").lower()


def _iso_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return ""


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Minimal frontmatter parser for simple `key: value` pairs.

    Deliberately not a full YAML parser (no new dependency) — Claude Code
    Skill/Agent frontmatter in practice is flat `name:`/`description:`
    pairs, optionally quoted, on single lines.
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    _, fm_text, body = parts
    meta: dict = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        meta[key] = value
    return meta, body


@dataclass
class _ReadResult:
    meta: dict
    body: str
    ok: bool
    error: str = ""


def _safe_read(path: Path) -> _ReadResult:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError, UnicodeError) as exc:
        return _ReadResult({}, "", False, f"Could not read {path}: {exc}")
    meta, body = _parse_frontmatter(text)
    return _ReadResult(meta, body, True)


class ClaudeCodeEnvironmentProvider(EnvironmentProvider):
    def __init__(self, project_root: Path | str | None = None, user_home: Path | str | None = None):
        self.project_root = Path(project_root).resolve() if project_root else None
        self.user_home = Path(user_home).resolve() if user_home else Path.home()

    def is_available(self) -> bool:
        return True

    def scan(self) -> EnvironmentSnapshot:
        errors: list[str] = []
        claude_md = self._safe(self._find_claude_md, errors, "CLAUDE.md discovery")
        skills = self._safe(self._find_skills, errors, "Skill discovery")
        agents = self._safe(self._find_agents, errors, "Agent discovery")
        mcp_servers = self._safe(self._find_mcp_servers, errors, "MCP discovery")

        return EnvironmentSnapshot(
            scanned_at=datetime.now().isoformat(timespec="seconds"),
            project_root=str(self.project_root) if self.project_root else None,
            claude_md=claude_md or [],
            skills=skills or [],
            agents=agents or [],
            mcp_servers=mcp_servers or [],
            errors=errors,
        )

    def _safe(self, fn, errors: list[str], label: str):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - a scan step must never crash the app
            errors.append(f"{label} failed: {exc}")
            return None

    # -- CLAUDE.md ------------------------------------------------------------
    def _find_claude_md(self) -> list[ClaudeMdInfo]:
        found: list[ClaudeMdInfo] = []
        seen: set[str] = set()

        def _add(path: Path, scope: Source) -> None:
            key = _normalize_path(str(path))
            if key in seen or not path.is_file():
                return
            seen.add(key)
            result = _safe_read(path)
            preview = redact_secrets(result.body.strip()[:PREVIEW_CHARS]) if result.ok else ""
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            found.append(ClaudeMdInfo(
                path=str(path), scope=scope, size_bytes=size,
                modified=_iso_mtime(path), preview=preview,
            ))

        if self.project_root:
            _add(self.project_root / "CLAUDE.md", Source.PROJECT)

            current = self.project_root.parent
            for _ in range(MAX_PARENT_WALK):
                if current is None or _normalize_path(str(current)) == _normalize_path(str(self.user_home)):
                    break
                _add(current / "CLAUDE.md", Source.PARENT)
                if current.parent == current:
                    break
                current = current.parent

        _add(self.user_home / ".claude" / "CLAUDE.md", Source.USER)
        return found

    # -- Skills -----------------------------------------------------------------
    def _find_skills(self) -> list[SkillInfo]:
        found: list[SkillInfo] = []
        roots = []
        if self.project_root:
            roots.append((self.project_root / ".claude" / "skills", Source.PROJECT))
        roots.append((self.user_home / ".claude" / "skills", Source.USER))

        for skills_dir, source in roots:
            if not skills_dir.is_dir():
                continue
            try:
                entries = sorted(skills_dir.iterdir())
            except OSError:
                continue
            for entry in entries:
                skill_md = entry / "SKILL.md" if entry.is_dir() else None
                if not skill_md or not skill_md.is_file():
                    continue
                result = _safe_read(skill_md)
                name = result.meta.get("name", entry.name) if result.ok else entry.name
                description = redact_secrets(result.meta.get("description", "")) if result.ok else ""
                found.append(SkillInfo(
                    name=name, path=str(skill_md), description=description,
                    source=source, modified=_iso_mtime(skill_md),
                ))
        return found

    # -- Agents -----------------------------------------------------------------
    def _find_agents(self) -> list[AgentInfo]:
        found: list[AgentInfo] = []
        roots = []
        if self.project_root:
            roots.append((self.project_root / ".claude" / "agents", Source.PROJECT))
        roots.append((self.user_home / ".claude" / "agents", Source.USER))

        for agents_dir, source in roots:
            if not agents_dir.is_dir():
                continue
            try:
                entries = sorted(agents_dir.glob("*.md"))
            except OSError:
                continue
            for path in entries:
                result = _safe_read(path)
                name = result.meta.get("name", path.stem) if result.ok else path.stem
                description = result.meta.get("description", "") if result.ok else ""
                if not description and result.ok:
                    first_line = next((l.strip() for l in result.body.splitlines() if l.strip()), "")
                    description = first_line[:PREVIEW_CHARS]
                found.append(AgentInfo(
                    name=name, path=str(path), description=redact_secrets(description),
                    source=source, modified=_iso_mtime(path),
                ))
        return found

    # -- MCP servers --------------------------------------------------------------
    def _find_mcp_servers(self) -> list[McpServerInfo]:
        found: list[McpServerInfo] = []

        if self.project_root:
            mcp_json = self.project_root / ".mcp.json"
            if mcp_json.is_file():
                found.extend(self._parse_mcp_config(mcp_json, Source.PROJECT))

        user_settings = self.user_home / ".claude" / "settings.json"
        if user_settings.is_file():
            found.extend(self._parse_mcp_config(user_settings, Source.USER))

        registry = self.user_home / ".claude.json"
        if self.project_root and registry.is_file():
            found.extend(self._parse_project_registry(registry))

        return found

    def _parse_mcp_config(self, path: Path, source: Source) -> list[McpServerInfo]:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            return []
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        if not isinstance(servers, dict):
            return []
        return [
            McpServerInfo(
                name=name,
                server_type=str(cfg.get("type", "stdio" if "command" in cfg else "unknown")),
                source=source,
                config_path=str(path),
            )
            for name, cfg in servers.items() if isinstance(cfg, dict)
        ]

    def _parse_project_registry(self, registry_path: Path) -> list[McpServerInfo]:
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            return []

        projects = data.get("projects") if isinstance(data, dict) else None
        if not isinstance(projects, dict):
            return []

        target = _normalize_path(str(self.project_root))
        entry = None
        for key, value in projects.items():
            if _normalize_path(key) == target:
                entry = value
                break
        if not isinstance(entry, dict):
            return []

        servers = entry.get("mcpServers")
        if not isinstance(servers, dict):
            return []

        enabled_list = set(entry.get("enabledMcpjsonServers") or [])
        disabled_list = set(entry.get("disabledMcpjsonServers") or [])

        results = []
        for name, cfg in servers.items():
            if not isinstance(cfg, dict):
                continue
            enabled = None
            if name in enabled_list:
                enabled = True
            elif name in disabled_list:
                enabled = False
            results.append(McpServerInfo(
                name=name,
                server_type=str(cfg.get("type", "stdio" if "command" in cfg else "unknown")),
                source=Source.PROJECT,
                config_path=str(registry_path),
                enabled=enabled,
            ))
        return results
