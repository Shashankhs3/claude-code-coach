# Changelog

All notable changes to the Claude Code Coach VS Code extension are
documented here.

## 0.3.1 — Pre-release

**Added** (since 0.3.0):

- **Bundled Coach service (Windows x64)**: the extension now ships its
  own self-contained Coach service executable (`CoachService.exe`) and
  starts it automatically in the background when no service (standalone
  or desktop) is already reachable — no Python install required.
  Supported on Windows x64 only; on any other platform or architecture
  the extension behaves exactly as before (connects to a desktop app or
  standalone service you run yourself), since no bundled executable
  ships for those targets.
- **Automatic startup**: `refresh()` and `Inspect Prompt` both attempt to
  start the bundled service before reporting `Offline`, governed by a
  new `claudeCodeCoach.autoStartService` setting (default on). A service
  you already run yourself, or the desktop app, is always preferred and
  never duplicated — the extension only starts its own service when
  nothing else answers the same validated discovery check (shape, live
  PID, compatible API version) every other code path here already uses.
- **Stale service recovery**: a leftover `service.json` pointing at a
  process that is no longer running (e.g. after a crash or forceful
  kill) is detected via a live PID check and no longer blocks a fresh
  start.
- **Safe existing-service reuse**: if a compatible service is already
  reachable — desktop app or a standalone service someone else started
  — the extension reuses it as-is and never spawns a second one.
- **Duplicate-start protection**: a short-TTL lock file prevents two VS
  Code windows racing to spawn their own copy of the bundled service;
  the OS-level port bind in the service itself is the real correctness
  backstop regardless of how many windows attempt to start one.

**Not included in this release**: the bundled auto-start service remains
Windows x64 only; macOS and Linux still require a desktop app or
standalone service you start yourself.

## 0.3.0 — Pre-release beta

**Added** (since 0.1.0):

- **`Claude Code Coach: Inspect Prompt`** command: runs a real Prompt
  Inspector pass (analysis + suggested rewrite + Approach Advisor
  recommendation) against the desktop app's deterministic analyzer, shown
  in the Coach panel. Includes a one-click **Copy Suggested Prompt**
  action and read-only opening of any Skill/Agent file the recommendation
  references.
- **Current Coaching** card in the panel: the single most relevant live
  coaching signal for the active session (context health, search-first
  workflow, verification, etc.) — the same signal vocabulary the desktop
  app's own coaching uses.
- **`Claude Code Coach: Pause Coaching`** / **`Resume Coaching`**
  commands, plus `claudeCodeCoach.coaching.notificationsEnabled` and
  `claudeCodeCoach.coaching.notificationLevel` (`highOnly` /
  `highAndMedium` / `off`) settings governing native notifications
  independently of the panel/status bar. Deduplicates repeat
  notifications for the same signal within a 15-minute window.
- New status bar state, `Attention`, shown when an actionable coaching
  signal is currently active (distinct from plain `Ready`).
- **`Claude Code Coach: Open Desktop Coach`** command: tells the user how
  to start the desktop app themselves. This is guidance text only —
  the extension cannot locate or launch the desktop app automatically,
  and does not claim to.

**Fixed:**

- Webview content could clip or fail to wrap on a narrow panel or with a
  long path/session ID/Skill path (added `overflow-wrap: anywhere` and
  `min-width: 0` on flex rows).

**Not included in this release** (unchanged from 0.1.0): Skill/Agent
*creation* and Workshop Mode have no VS Code UI yet — both remain
desktop-only.

## 0.1.0 — Initial beta

First release. Establishes the local bridge between VS Code and the
Claude Code Coach desktop application.

**Added:**

- Local service discovery (reads the desktop app's `service.json`) with
  automatic re-detection when the desktop app starts, stops, or restarts.
- Token-authenticated HTTP connection to the desktop app's local Coach
  service (`127.0.0.1` only).
- Status bar item with real connection states: `Connecting`, `Ready`,
  `Offline`, `Paused`.
- One command, **Claude Code Coach: Open Coach**, opening a panel that
  shows real connection status, workspace, runtime state, session
  summary, and environment counts.
- Live refresh via a local file-change signal (near-instant on real
  Claude Code activity) plus a periodic fallback poll.
- Automatic reconnection when the desktop app becomes available after
  the extension was already running (no reload required).
- A `claudeCodeCoach.pollIntervalSeconds` setting for the fallback poll
  interval.

**Not included in this release** (see README's Known Limitations):
Prompt Inspector, Suggested Prompt, Approach Advisor, Skill/Agent
creation, Context Health, Verification Coach, and Workshop Mode have no
VS Code UI yet.
