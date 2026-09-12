import * as vscode from "vscode";
import { CoachClient, InvalidRequestError, getLastDiscoveryIssue, readDiscovery } from "./coachClient";
import { CoachPanel } from "./coachPanel";
import { CoachStatusBar } from "./statusBar";
import {
  NotificationLevelSetting,
  deriveCoachStatus,
  notificationMessage,
  pickPrimarySignal,
  shouldNotify,
} from "./coaching";
import { CoachingStateStore } from "./coachingState";
import { FileSignalWatcher } from "./fileSignal";
import { ConnectionStatus, RuntimeSignal } from "./types";
import { removeWindowRegistryEntry, writeWindowRegistryEntry } from "./windowRegistry";

const DEFAULT_POLL_SECONDS = 5;

let statusBar: CoachStatusBar | undefined;
let signalWatcher: FileSignalWatcher | undefined;
let pollTimer: ReturnType<typeof setInterval> | undefined;
let currentState: ConnectionStatus = "connecting";

/** Phase 3B settings — read fresh on every refresh tick so a user changing
 * Settings takes effect on the very next poll, no reload required. */
function notificationSettings(): { enabled: boolean; level: NotificationLevelSetting } {
  const cfg = vscode.workspace.getConfiguration("claudeCodeCoach.coaching");
  return {
    enabled: cfg.get<boolean>("notificationsEnabled", true),
    level: cfg.get<NotificationLevelSetting>("notificationLevel", "highOnly"),
  };
}

export function activate(context: vscode.ExtensionContext): void {
  const client = new CoachClient();
  const coachingState = new CoachingStateStore(context.globalState);
  statusBar = new CoachStatusBar();

  writeWindowRegistryEntry();

  const refresh = async () => {
    const discovery = readDiscovery();
    if (!discovery) {
      // getLastDiscoveryIssue() is undefined for the routine "nothing is
      // running yet" case and set for a specific problem (stale discovery
      // file, incompatible api_version — Step 4) — setState/statusBar
      // shows the specific message when there is one.
      setState(deriveCoachStatus({ reachable: false, paused: false, primary: undefined }), getLastDiscoveryIssue() ?? undefined);
      CoachPanel.refreshIfOpen(client);
      return;
    }
    try {
      await client.health();
    } catch {
      setState(deriveCoachStatus({ reachable: false, paused: false, primary: undefined }));
      CoachPanel.refreshIfOpen(client);
      return;
    }

    // Section 4/11: coaching evaluation runs on every tick, independent of
    // whether the panel is open, so Attention/notifications work in the
    // background too. A failed/malformed session fetch is treated as "no
    // signal this tick" — never crashes, never fabricates a warning.
    //
    // Phase 4E (docs/SHARED_COACH_STATE.md §5): `paused` is now the
    // backend's own shared `coaching_paused` flag, not a local
    // vscode.Memento value — so Desktop pausing (or another VS Code
    // window) is observed here on the very next poll tick. That means
    // session() must always be called, even while paused, just to learn
    // the current paused state — the panel already did this unconditionally.
    //
    // primary_signal prefers the backend's own selection (§3/4); an older/
    // incompatible service that omits the field falls back to this
    // extension's own pickPrimarySignal() over the same signals list —
    // Step 21 compatibility, not a second scoring system.
    //
    // deriveCoachStatus() is the single source of truth for whether the
    // *current* primary signal counts as Attention — the same function the
    // status bar, and the panel, both key off of — so this can never
    // disagree with what the panel is showing for the same /session
    // response. See coaching.ts.
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    try {
      const session = await client.session(workspaceFolder);
      const paused = session.coaching_paused ?? false;
      if (paused) {
        setState(deriveCoachStatus({ reachable: true, paused: true, primary: undefined }));
      } else {
        const primary =
          session.primary_signal !== undefined
            ? (session.primary_signal ?? undefined)
            : pickPrimarySignal(session.signals);
        setState(deriveCoachStatus({ reachable: true, paused: false, primary }));
        maybeNotify(client, coachingState, workspaceFolder, session.session?.session_id, primary);
      }
    } catch {
      // Connection is fine (health succeeded above) but the session call
      // itself failed — fall back to plain Ready rather than guessing.
      setState(deriveCoachStatus({ reachable: true, paused: false, primary: undefined }));
    }
    // Refreshed regardless of outcome: an already-open panel must show the
    // real state too, not keep displaying the last-known-good data.
    CoachPanel.refreshIfOpen(client);
  };

  signalWatcher = new FileSignalWatcher();
  signalWatcher.start();
  signalWatcher.onDidChange(() => {
    void refresh();
  });

  const pollSeconds =
    vscode.workspace.getConfiguration("claudeCodeCoach").get<number>("pollIntervalSeconds") ??
    DEFAULT_POLL_SECONDS;
  pollTimer = setInterval(() => {
    void refresh();
  }, Math.max(2, pollSeconds) * 1000);

  // Section 17: switching projects must refresh immediately, not wait for
  // the next poll tick — CoachPanel.refresh() itself clears any prompt
  // inspection that belonged to the previous workspace.
  const foldersListener = vscode.workspace.onDidChangeWorkspaceFolders(() => {
    writeWindowRegistryEntry();
    void refresh();
  });

  const openCommand = vscode.commands.registerCommand("claudeCodeCoach.openCoach", () => {
    CoachPanel.createOrShow(client, coachingState);
  });

  const inspectCommand = vscode.commands.registerCommand("claudeCodeCoach.inspectPrompt", () =>
    inspectPrompt(client, coachingState),
  );

  const copySuggestionCommand = vscode.commands.registerCommand(
    "claudeCodeCoach.copySuggestedPrompt",
    () => copySuggestedPrompt(),
  );

  const openSkillOrAgentCommand = vscode.commands.registerCommand(
    "claudeCodeCoach.openSkillOrAgentPath",
    (path: unknown) => openSkillOrAgentPath(path),
  );

  const openDesktopCoachCommand = vscode.commands.registerCommand(
    "claudeCodeCoach.openDesktopCoach",
    () => openDesktopCoach(),
  );

  // Section 10 / Phase 4E (docs/SHARED_COACH_STATE.md §5): pause/resume are
  // now backend-shared, not a local vscode.Memento flag — pausing here
  // also pauses Desktop (and any other VS Code window pointed at the same
  // standalone service), and vice versa. "Already paused"/"not paused" is
  // checked against `currentState` (this extension's own last-observed,
  // backend-sourced state) rather than a second network round trip.
  // Requires a reachable service — there is nothing to pause remotely
  // while offline, so that case is reported plainly rather than silently
  // no-op'd.
  const pauseCommand = vscode.commands.registerCommand("claudeCodeCoach.pauseCoaching", async () => {
    if (currentState === "paused") {
      vscode.window.setStatusBarMessage("Claude Code Coach: coaching is already paused", 3000);
      return;
    }
    try {
      await client.setPaused(true);
    } catch {
      vscode.window.setStatusBarMessage("Claude Code Coach: service unavailable — could not pause", 3000);
      return;
    }
    vscode.window.setStatusBarMessage("Claude Code Coach: coaching paused", 3000);
    void refresh();
  });
  const resumeCommand = vscode.commands.registerCommand("claudeCodeCoach.resumeCoaching", async () => {
    if (currentState !== "paused") {
      vscode.window.setStatusBarMessage("Claude Code Coach: coaching is not paused", 3000);
      return;
    }
    try {
      await client.setPaused(false);
    } catch {
      vscode.window.setStatusBarMessage("Claude Code Coach: service unavailable — could not resume", 3000);
      return;
    }
    vscode.window.setStatusBarMessage("Claude Code Coach: coaching resumed", 3000);
    void refresh();
  });

  context.subscriptions.push(
    statusBar,
    signalWatcher,
    openCommand,
    inspectCommand,
    copySuggestionCommand,
    openSkillOrAgentCommand,
    openDesktopCoachCommand,
    pauseCommand,
    resumeCommand,
    foldersListener,
    new vscode.Disposable(() => {
      if (pollTimer) {
        clearInterval(pollTimer);
      }
    }),
  );

  void refresh();
}

export function deactivate(): void {
  removeWindowRegistryEntry();
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = undefined;
  }
}

function setState(state: ConnectionStatus, detail?: string): void {
  currentState = state;
  statusBar?.set(state, detail);
}

/**
 * Section 2/3/14: fires a native notification for the current primary
 * signal only when shouldNotify() says every rule (paused, settings,
 * tier, dedup) is satisfied — see coaching.ts for the exact truth table.
 * A signal that doesn't qualify simply isn't notified; the panel (if open)
 * still shows it via CoachPanel.refreshIfOpen in the caller.
 */
function maybeNotify(
  client: CoachClient,
  coachingState: CoachingStateStore,
  workspaceFolder: string | undefined,
  sessionId: string | undefined,
  primary: RuntimeSignal | undefined,
): void {
  if (!primary || !workspaceFolder || !sessionId) {
    return;
  }
  const { enabled, level } = notificationSettings();
  const recentlyNotified = coachingState.wasRecentlyNotified(workspaceFolder, sessionId, primary.kind);
  if (
    !shouldNotify(primary, {
      notificationsEnabled: enabled,
      notificationLevel: level,
      paused: false, // already checked by the caller before reaching here
      recentlyNotified,
    })
  ) {
    return;
  }
  void coachingState.markNotified(workspaceFolder, sessionId, primary.kind);
  void vscode.window
    .showWarningMessage(notificationMessage(primary), "View Details", "Dismiss")
    .then((choice) => {
      if (choice === "View Details") {
        CoachPanel.createOrShow(client, coachingState);
      }
    });
}

/**
 * Section 3: "Claude Code Coach: Inspect Prompt". Opens the panel (if not
 * already open) and asks for a prompt to run through the real V5
 * analyzer/suggester/approach-advisor — never through anything local to
 * the extension. If the Coach service isn't reachable, says so plainly
 * rather than prompting for text that could never be sent anywhere.
 */
async function inspectPrompt(client: CoachClient, coachingState: CoachingStateStore): Promise<void> {
  if (!readDiscovery()) {
    void vscode.window.showWarningMessage(
      "Claude Code Coach is offline — start the Coach service " +
        "(`python -m claude_code_coach.service`, or the desktop app) to inspect a prompt.",
    );
    return;
  }
  const prompt = await vscode.window.showInputBox({
    title: "Claude Code Coach: Inspect Prompt",
    prompt: "Enter a prompt to analyze",
    placeHolder: "e.g. Fix the login timeout in src/auth/login.ts",
    ignoreFocusOut: true,
  });
  if (!prompt || !prompt.trim()) {
    return;
  }
  CoachPanel.createOrShow(client, coachingState);
  try {
    await CoachPanel.runInspection(client, prompt);
  } catch (err) {
    const message = err instanceof InvalidRequestError ? err.message : "Coach temporarily unavailable.";
    void vscode.window.showWarningMessage(message);
  }
}

/** The suggested-prompt "Copy" action inside the panel. Uses a transient
 * status-bar message rather than a toast notification — matching the
 * "quiet by default" UX principle (section 19): this confirms a direct
 * user action, it never fires on its own. */
async function copySuggestedPrompt(): Promise<void> {
  const inspection = CoachPanel.getLastInspection();
  const text = inspection?.suggestion.suggested_text;
  if (!text) {
    return;
  }
  await vscode.env.clipboard.writeText(text);
  vscode.window.setStatusBarMessage("Claude Code Coach: suggested prompt copied", 3000);
}

/** Read-only: opens a Skill/Agent file the Approach Advisor detected, for
 * viewing. Never writes to it, never creates or modifies anything — see
 * section 6's explicit rule. */
async function openSkillOrAgentPath(pathArg: unknown): Promise<void> {
  const path = Array.isArray(pathArg) ? pathArg[0] : pathArg;
  if (typeof path !== "string" || !path) {
    return;
  }
  try {
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(path));
    await vscode.window.showTextDocument(doc, { preview: true });
  } catch {
    void vscode.window.showWarningMessage(`Could not open ${path}.`);
  }
}

/**
 * Section 14 / Phase 4B Step 15: the escape hatch to the full desktop
 * experience — "Open Desktop Coach" means *open the desktop UI*, never
 * "start the only thing that makes the extension work" (the extension
 * itself no longer needs the desktop app at all, see Phase 4A/4B). VS Code
 * has no reliable, portable way to locate an arbitrary user's separately
 * installed desktop application, and hardcoding a path would only work on
 * the machine it was written on — so this never guesses a path.
 *
 * Prior (Phase 2/3) behavior here checked readDiscovery() and reported
 * "desktop app is already running" when a service was reachable — that
 * became actively wrong once a standalone service (Phase 4A) could be the
 * one answering: reachability no longer implies the desktop specifically
 * is open, and the discovery contract carries no field that distinguishes
 * the two. Always giving the same honest guidance is the correct fix, not
 * a regression.
 */
async function openDesktopCoach(): Promise<void> {
  void vscode.window.showInformationMessage(
    "Start the Claude Code Coach desktop application from wherever you normally launch it — " +
      "VS Code cannot locate, launch, or detect it automatically. (A Coach service being " +
      "reachable does not by itself mean the desktop app is the one running — it may be the " +
      "standalone `python -m claude_code_coach.service` instead.)",
  );
}

/** Exposed for tests only. */
export function _getCurrentStateForTests(): ConnectionStatus {
  return currentState;
}
