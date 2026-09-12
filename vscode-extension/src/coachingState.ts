import * as vscode from "vscode";

/**
 * Phase 3B: lightweight, non-sensitive state for the coaching intervention
 * layer — pause/resume and notification deduplication. Backed by a
 * vscode.Memento (context.globalState in production; a fake in tests) —
 * no second database, per section 17.
 *
 * Pause is deliberately global (context.globalState is one store per
 * extension per machine, shared across every VS Code window) rather than
 * per-workspace — a documented scope choice, not an oversight. See
 * docs/VSCODE_INTEGRATION.md.
 *
 * Deduplication never stores prompt text or file content — only the signal
 * `kind`, the workspace folder path, the session id, and a timestamp
 * (section 3/18).
 */

const PAUSED_KEY = "claudeCodeCoach.coachingPaused";
const NOTIFIED_PREFIX = "claudeCodeCoach.lastNotified::";

/** Dedup window: a signal already notified for the same (workspace, session,
 * kind) within this many milliseconds is suppressed. 15 minutes is long
 * enough to avoid repeat toasts for a condition that's still true on every
 * ~5s poll tick, short enough that a genuinely still-relevant warning can
 * surface again after a break. */
export const DEDUPE_WINDOW_MS = 15 * 60 * 1000;

export class CoachingStateStore {
  constructor(private readonly memento: vscode.Memento) {}

  isPaused(): boolean {
    return this.memento.get<boolean>(PAUSED_KEY, false);
  }

  setPaused(paused: boolean): Thenable<void> {
    return this.memento.update(PAUSED_KEY, paused);
  }

  private dedupeKey(workspaceFolder: string, sessionId: string, kind: string): string {
    return `${NOTIFIED_PREFIX}${workspaceFolder}::${sessionId}::${kind}`;
  }

  wasRecentlyNotified(
    workspaceFolder: string,
    sessionId: string,
    kind: string,
    now: number = Date.now(),
  ): boolean {
    const last = this.memento.get<number>(this.dedupeKey(workspaceFolder, sessionId, kind), 0);
    return now - last < DEDUPE_WINDOW_MS;
  }

  markNotified(
    workspaceFolder: string,
    sessionId: string,
    kind: string,
    now: number = Date.now(),
  ): Thenable<void> {
    return this.memento.update(this.dedupeKey(workspaceFolder, sessionId, kind), now);
  }
}
