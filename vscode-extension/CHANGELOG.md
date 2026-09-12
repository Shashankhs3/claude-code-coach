# Changelog

All notable changes to the Claude Code Coach VS Code extension are
documented here.

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
