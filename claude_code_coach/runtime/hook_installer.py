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
  this installer would write, so it can never remove a hook it didn't add.

Frozen (packaged) builds need a second decision this file makes in one
place only (see `hook_command()`): running from source, the hook is
`sys.executable` + this repo's `hook_receiver.py`. That breaks under
PyInstaller two different ways — `sys.executable` there is this app's own
GUI exe, not a Python interpreter that can be handed a script to run, and
`Path(__file__)` for a frozen module resolves inside a temp extraction
directory that PyInstaller deletes the moment this process exits, which is
fatal for a hook Claude Code invokes long after the app has closed. The
packaged build instead ships a second, tiny standalone executable
(`hook_receiver.exe`, built from this same `hook_receiver.py`, see
`packaging/build.ps1`) at a stable path next to the app, and the hook
command becomes that executable directly, no interpreter involved.
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


def _frozen_receiver_exe() -> Path:
    """Stable, persistent path to the standalone receiver exe a packaged
    build ships alongside itself — see the module docstring for why a
    frozen app can't use `sys.executable` + `receiver_path()` instead."""
    name = "hook_receiver.exe" if os.name == "nt" else "hook_receiver"
    return Path(sys.executable).resolve().parent / "hook_receiver" / name


def hook_command() -> tuple[str, list[str]]:
    """(command, args) Claude Code should invoke for this app's hook — the
    one place this is decided, so install/uninstall/status can never
    disagree with each other about what "our hook" looks like."""
    if getattr(sys, "frozen", False):
        return (str(_frozen_receiver_exe()), [])
    return (sys.executable, [receiver_path()])


def _expected_hook() -> dict:
    command, args = hook_command()
    return {"type": "command", "command": command, "args": args}


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


def _is_our_hook(hook: dict, expected: dict) -> bool:
    return (
        isinstance(hook, dict)
        and hook.get("type") == expected["type"]
        and hook.get("command") == expected["command"]
        and (hook.get("args") or []) == expected["args"]
    )


def install_hooks(settings_path: Path) -> dict:
    """Add this app's hook command to every supported event. Idempotent."""
    settings_path = Path(settings_path)
    settings = _read_json_safe(settings_path)
    hooks_section = settings.setdefault("hooks", {})

    expected = _expected_hook()
    added: list[str] = []

    for event_name in HOOK_EVENTS:
        entry_list = hooks_section.setdefault(event_name, [])
        if not isinstance(entry_list, list):
            continue  # unexpected shape in an existing file — leave it alone

        already_installed = any(
            isinstance(group, dict)
            and any(_is_our_hook(h, expected) for h in group.get("hooks", []))
            for group in entry_list
        )
        if already_installed:
            continue

        entry_list.append({"matcher": "*", "hooks": [dict(expected)]})
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

    expected = _expected_hook()
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
                h for h in group.get("hooks", []) if not _is_our_hook(h, expected)
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
    expected = _expected_hook()
    for entry_list in hooks_section.values():
        if not isinstance(entry_list, list):
            continue
        for group in entry_list:
            if isinstance(group, dict) and any(
                _is_our_hook(h, expected) for h in group.get("hooks", [])
            ):
                return True
    return False
