import * as vscode from "vscode";
import { ConnectionStatus } from "./types";

/**
 * Real states only, matching the states the client can actually observe:
 *  - connecting: extension just activated / just lost then is re-probing
 *  - ready:      service reachable, health check succeeded, no HIGH-tier
 *                coaching signal is currently active
 *  - offline:    no Coach service is reachable — service.json absent,
 *                stale (Phase 4A: its PID is dead), reporting an
 *                incompatible api_version, or just not listening yet.
 *                Not specific to the desktop app: a standalone
 *                `python -m claude_code_coach.service` process (Phase 4A)
 *                satisfies "Ready" exactly the same way.
 *  - paused:     the user ran "Claude Code Coach: Pause Coaching"
 *                (coachingState.ts) — no notifications, no Attention state
 *  - attention:  (Phase 3B) a MEDIUM- or HIGH-tier RuntimeSignal is the
 *                current primary signal for this workspace's session —
 *                never shown for a LOW-level/positive runtime event.
 *                Derived by coaching.ts's deriveCoachStatus(), the same
 *                function the notification path and (via
 *                pickPrimarySignal) the panel key off of, so this can
 *                never disagree with what the panel is showing.
 * Every state uses a distinct icon glyph, not just color, so Attention and
 * Offline remain distinguishable in any theme (spec section 19).
 */
export class CoachStatusBar implements vscode.Disposable {
  private readonly item: vscode.StatusBarItem;

  constructor() {
    this.item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    this.item.command = "claudeCodeCoach.openCoach";
    this.item.show();
    this.set("connecting");
  }

  /** `detail`, when given, replaces the default offline tooltip — used to
   * surface a specific diagnostic (Step 4: e.g. "stale discovery file" or
   * "incompatible api_version") instead of the generic message, via
   * coachClient.ts's getLastDiscoveryIssue(). Ignored for every other
   * status. */
  set(status: ConnectionStatus, detail?: string): void {
    switch (status) {
      case "connecting":
        this.item.text = "$(sync~spin) Coach: Connecting";
        this.item.tooltip = "Claude Code Coach: looking for a local Coach service...";
        this.item.backgroundColor = undefined;
        break;
      case "ready":
        this.item.text = "$(check) Coach: Ready ✓";
        this.item.tooltip = "Claude Code Coach: connected to the local Coach service.";
        this.item.backgroundColor = undefined;
        break;
      case "offline":
        this.item.text = "$(circle-slash) Coach: Offline";
        this.item.tooltip = detail ?? "Claude Code Coach: no local Coach service is running.";
        this.item.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
        break;
      case "paused":
        this.item.text = "$(debug-pause) Coach: Paused";
        this.item.tooltip = "Claude Code Coach: paused. Run 'Claude Code Coach: Resume Coaching' to re-enable.";
        this.item.backgroundColor = undefined;
        break;
      case "attention":
        this.item.text = "$(alert) Coach: Attention";
        this.item.tooltip = "Claude Code Coach: an actionable coaching signal needs attention. Open the panel for details.";
        this.item.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
        break;
    }
  }

  dispose(): void {
    this.item.dispose();
  }
}
