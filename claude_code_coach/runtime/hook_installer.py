"""Installs/removes this app's hook commands in a Claude Code settings.json.

This is the one place in the whole app that writes to real Claude Code
configuration, so it is held to a higher bar than the read-only V3.1
scanner: never silent, never automatic, and always reversible.

- Existing hooks (anything not written by this installer) are always
  preserved — entries are appended into each event's hook list, never
  replacing it.
- Writes are atomic (temp file + os.replace) so a crash mid-write can't
  corrupt the user's real, working configuration.
- A malformed existing settings.json is never overwritten blindly — the
  caller gets a clear error instead, so a person can fix or back up the
  file themselves.
- Uninstall matches only entries whose command+args exactly equal what
  this installer would write (this interpreter + this receiver script's
  absolute path), so it can never remove a hook it didn't add.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# The core, high-confidence event set this app actually supports (see
# runtime/models.py's module docstring for the "why these and not others").
HOOK_EVENTS = (
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse",
    "PostToolUse", "Stop", "SubagentStop", "PreCompact", "Notification",
    "PermissionRequest",
)


def receiver_path() -> str:
    return str(Path(__file__).resolve().with_name("hook_receiver.py"))


def _read_json_safe(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(
            f"{path} contains invalid JSON and was left untouched: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object; left untouched.")
    return data


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".coach_settings_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass


def _is_our_hook(hook: dict, interpreter: str, receiver: str) -> bool:
    return (
        isinstance(hook, dict)
        and hook.get("type") == "command"
        and hook.get("command") == interpreter
        and receiver in (hook.get("args") or [])
    )


def install_hooks(settings_path: Path) -> dict:
    """Add this app's hook command to every supported event. Idempotent."""
    settings_path = Path(settings_path)
    settings = _read_json_safe(settings_path)
    hooks_section = settings.setdefault("hooks", {})

    interpreter = sys.executable
    receiver = receiver_path()
    added: list[str] = []

    for event_name in HOOK_EVENTS:
        entry_list = hooks_section.setdefault(event_name, [])
        if not isinstance(entry_list, list):
            continue  # unexpected shape in an existing file — leave it alone

        already_installed = any(
            isinstance(group, dict)
            and any(_is_our_hook(h, interpreter, receiver) for h in group.get("hooks", []))
            for group in entry_list
        )
        if already_installed:
            continue

        entry_list.append({
            "matcher": "*",
            "hooks": [{"type": "command", "command": interpreter, "args": [receiver]}],
        })
        added.append(event_name)

    _write_json_atomic(settings_path, settings)
    return {"path": str(settings_path), "added_events": added}


def uninstall_hooks(settings_path: Path) -> dict:
    """Remove only this app's hook entries. Leaves everything else untouched."""
    settings_path = Path(settings_path)
    settings = _read_json_safe(settings_path)
    hooks_section = settings.get("hooks")
    if not isinstance(hooks_section, dict):
        return {"path": str(settings_path), "removed_events": []}

    interpreter = sys.executable
    receiver = receiver_path()
    removed: list[str] = []

    for event_name in list(hooks_section.keys()):
        entry_list = hooks_section.get(event_name)
        if not isinstance(entry_list, list):
            continue

        new_entry_list = []
        changed = False
        for group in entry_list:
            if not isinstance(group, dict):
                new_entry_list.append(group)
                continue
            remaining_hooks = [
                h for h in group.get("hooks", []) if not _is_our_hook(h, interpreter, receiver)
            ]
            if len(remaining_hooks) != len(group.get("hooks", [])):
                changed = True
            if remaining_hooks:
                new_group = dict(group)
                new_group["hooks"] = remaining_hooks
                new_entry_list.append(new_group)
            # else: this group was entirely ours — drop it

        if changed:
            removed.append(event_name)
        if new_entry_list:
            hooks_section[event_name] = new_entry_list
        else:
            del hooks_section[event_name]

    _write_json_atomic(settings_path, settings)
    return {"path": str(settings_path), "removed_events": removed}


def hooks_installed_in(settings_path: Path) -> bool:
    try:
        settings = _read_json_safe(Path(settings_path))
    except ValueError:
        return False
    hooks_section = settings.get("hooks")
    if not isinstance(hooks_section, dict):
        return False
    interpreter = sys.executable
    receiver = receiver_path()
    for entry_list in hooks_section.values():
        if not isinstance(entry_list, list):
            continue
        for group in entry_list:
            if isinstance(group, dict) and any(
                _is_our_hook(h, interpreter, receiver) for h in group.get("hooks", [])
            ):
                return True
    return False
