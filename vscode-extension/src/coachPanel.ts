import * as vscode from "vscode";
import { CoachClient, InvalidRequestError, ServiceUnavailableError } from "./coachClient";
import { pickPrimarySignal } from "./coaching";
import { CoachingStateStore } from "./coachingState";
import {
  ApproachRecommendation,
  EnvironmentResponse,
  PromptInspection,
  RuntimeSignal,
  SessionResponse,
  SkillOrAgentInfo,
  StatusResponse,
} from "./types";

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** high > medium > low, matching V5's own confidence/level vocabulary —
 * no new scoring scheme, just picking the existing field's max. */
const LEVEL_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };

function pickPrimaryRecommendation(recs: ApproachRecommendation[]): ApproachRecommendation | undefined {
  const real = recs.filter((r) => r.kind !== "normal_session");
  if (real.length === 0) {
    return undefined;
  }
  return [...real].sort((a, b) => (LEVEL_ORDER[a.level] ?? 9) - (LEVEL_ORDER[b.level] ?? 9))[0];
}

function healthColor(health: number): string {
  if (health >= 70) return "var(--vscode-testing-iconPassed, #2ea043)";
  if (health >= 40) return "var(--vscode-statusBarItem-warningBackground, #cca700)";
  return "var(--vscode-testing-iconFailed, #f14c4c)";
}

/** Command URIs the panel is allowed to invoke — nothing else, and none of
 * them write to disk or execute user input; see extension.ts for what each
 * one actually does. */
export const PANEL_COMMAND_IDS = [
  "claudeCodeCoach.inspectPrompt",
  "claudeCodeCoach.copySuggestedPrompt",
  "claudeCodeCoach.openSkillOrAgentPath",
  "claudeCodeCoach.openDesktopCoach",
] as const;

function commandUri(command: string, args?: unknown): string {
  const query = args !== undefined ? `?${encodeURIComponent(JSON.stringify(args))}` : "";
  return `command:${command}${query}`;
}

interface RenderState {
  state: "connecting" | "connected" | "offline";
  status?: StatusResponse;
  session?: SessionResponse;
  environment?: EnvironmentResponse;
  inspection?: PromptInspection;
  inspectionError?: string;
  message?: string;
  workspaceFolder?: string;
}

/**
 * The Phase 3 Workflow Coach panel: a real "what should I do next"
 * summary, built entirely from existing V5 evidence (runtime signals,
 * Approach Advisor, environment discovery) plus, on request, a real
 * Prompt Inspector/Suggested Prompt/Approach run for text the user
 * supplies. No analysis logic lives here — every judgment call (which
 * signal is real, what confidence a Skill match has, whether a rewrite is
 * safe) was already made by V5; this only picks which single evidence
 * item to lead with and renders the rest underneath.
 */
export class CoachPanel {
  private static current: CoachPanel | undefined;
  private readonly panel: vscode.WebviewPanel;
  private disposed = false;
  private lastInspection: PromptInspection | undefined;
  private lastInspectionError: string | undefined;
  private lastWorkspaceFolder: string | undefined;

  static createOrShow(client: CoachClient, coachingState: CoachingStateStore): CoachPanel {
    if (CoachPanel.current && !CoachPanel.current.disposed) {
      CoachPanel.current.panel.reveal();
      void CoachPanel.current.refresh(client);
      return CoachPanel.current;
    }
    const panel = vscode.window.createWebviewPanel(
      "claudeCodeCoach",
      "Claude Code Coach",
      vscode.ViewColumn.Beside,
      { enableScripts: false, enableCommandUris: [...PANEL_COMMAND_IDS] },
    );
    CoachPanel.current = new CoachPanel(panel, coachingState);
    void CoachPanel.current.refresh(client);
    return CoachPanel.current;
  }

  /** Called from the signal-file/poll refresh path in extension.ts. A
   * no-op when no panel is open — the panel only re-fetches while it's
   * actually visible to someone, never in the background. */
  static refreshIfOpen(client: CoachClient): void {
    if (CoachPanel.current && !CoachPanel.current.disposed) {
      void CoachPanel.current.refresh(client);
    }
  }

  /** Runs a real Prompt Inspector pass (analyze + suggest + approach) for
   * `prompt` against whichever panel is currently open, or does nothing
   * if none is. Called from the claudeCodeCoach.inspectPrompt command. */
  static async runInspection(client: CoachClient, prompt: string): Promise<void> {
    if (!CoachPanel.current || CoachPanel.current.disposed) {
      return;
    }
    await CoachPanel.current.inspectPrompt(client, prompt);
  }

  static getLastInspection(): PromptInspection | undefined {
    return CoachPanel.current && !CoachPanel.current.disposed
      ? CoachPanel.current.lastInspection
      : undefined;
  }

  /** Exposed for tests only — reads the rendered HTML without needing the
   * real VS Code webview host to expose panel internals another way. */
  getHtmlForTests(): string {
    return this.panel.webview.html;
  }

  /** Exposed for tests only. */
  getLastInspectionForTests(): PromptInspection | undefined {
    return this.lastInspection;
  }

  /** Closes the underlying webview panel — same effect as the user closing
   * the tab. Mainly useful for test cleanup between cases. */
  dispose(): void {
    this.panel.dispose();
  }

  // Phase 4E: pause is no longer read from CoachingStateStore (it's
  // backend-shared now — see renderCurrentCoaching's use of
  // session.coaching_paused), but the parameter stays for call-site
  // compatibility (extension.ts constructs one CoachingStateStore and
  // passes it to every CoachPanel.createOrShow call for notification
  // dedup, unrelated to this panel itself).
  private constructor(panel: vscode.WebviewPanel, _coachingState: CoachingStateStore) {
    this.panel = panel;
    this.panel.onDidDispose(() => {
      this.disposed = true;
      if (CoachPanel.current === this) {
        CoachPanel.current = undefined;
      }
    });
    this.panel.webview.html = this.render({ state: "connecting" });
  }

  private lastFetched: { status: StatusResponse; session: SessionResponse; environment?: EnvironmentResponse; workspaceFolder?: string } | undefined;

  async refresh(client: CoachClient): Promise<void> {
    if (this.disposed) {
      return;
    }
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;

    // Section 17: a prompt inspection is scoped to the workspace it was
    // run against — switching projects must never show Project A's
    // Skill/Agent/approach guidance while looking at Project B.
    if (this.lastWorkspaceFolder !== undefined && this.lastWorkspaceFolder !== workspaceFolder) {
      this.lastInspection = undefined;
      this.lastInspectionError = undefined;
    }
    this.lastWorkspaceFolder = workspaceFolder;

    try {
      const [status, session, environment] = await Promise.all([
        client.status(workspaceFolder),
        client.session(workspaceFolder),
        client.environment(workspaceFolder).catch(() => undefined),
      ]);
      if (this.disposed) {
        return;
      }
      this.lastFetched = { status, session, environment, workspaceFolder };
      this.panel.webview.html = this.render({
        state: "connected",
        status,
        session,
        environment,
        inspection: this.lastInspection,
        inspectionError: this.lastInspectionError,
        workspaceFolder,
      });
    } catch (err) {
      if (this.disposed) {
        return;
      }
      const message = err instanceof ServiceUnavailableError ? err.message : String(err);
      this.panel.webview.html = this.render({ state: "offline", message, workspaceFolder });
    }
  }

  private async inspectPrompt(client: CoachClient, prompt: string): Promise<void> {
    if (this.disposed) {
      return;
    }
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    try {
      const [analysis, suggestion, approach] = await Promise.all([
        client.analyze(prompt),
        client.suggest(prompt),
        client.approach(prompt, { projectRoot: workspaceFolder, cwd: workspaceFolder }),
      ]);
      this.lastInspection = { prompt, analysis, suggestion, approach };
      this.lastInspectionError = undefined;
    } catch (err) {
      this.lastInspection = undefined;
      this.lastInspectionError =
        err instanceof InvalidRequestError || err instanceof ServiceUnavailableError
          ? err.message
          : "Coach temporarily unavailable.";
    }
    await this.refresh(client);
  }

  private render(data: RenderState): string {
    const style = `
      /* UI stabilization pass (docs/UI_STABILIZATION_AUDIT.md, Issues 6/8/19):
         overflow-wrap: anywhere (not break-word) also shrinks the *intrinsic
         minimum content size* the browser uses to size flex children — the
         real cause of a long workspace path, session ID, or coaching message
         forcing the row (and the whole panel) wider than a narrow sidebar
         instead of wrapping onto another line. Inherited by every element
         below, so this one rule covers .row values, coaching messages, and
         the prompt quote alike. */
      body { font-family: var(--vscode-font-family); padding: 1.2em; color: var(--vscode-foreground);
             overflow-wrap: anywhere; }
      h2 { margin-top: 1.6em; margin-bottom: 0.5em; font-size: 0.92em; text-transform: uppercase;
           letter-spacing: 0.05em; opacity: 0.7; border-bottom: 1px solid var(--vscode-widget-border, #4448);
           padding-bottom: 0.35em; }
      .row { display: flex; justify-content: space-between; padding: 0.15em 0; gap: 1em; }
      .row > * { min-width: 0; }
      .label { opacity: 0.75; flex-shrink: 0; }
      .badge { display: inline-block; padding: 0.1em 0.6em; border-radius: 1em; font-size: 0.85em; }
      .badge.ok { background: var(--vscode-testing-iconPassed, #2ea043); color: white; }
      .badge.warn { background: var(--vscode-statusBarItem-warningBackground, #cca700); color: black; }
      .empty { opacity: 0.6; font-style: italic; }
      .coaching-card { border-left: 3px solid var(--vscode-focusBorder); padding: 0.6em 0.9em;
                        background: var(--vscode-textBlockQuote-background, #4441); border-radius: 3px; }
      .coaching-card.good { border-left-color: var(--vscode-testing-iconPassed, #2ea043); }
      .coaching-card.high { border-left-color: var(--vscode-testing-iconFailed, #f14c4c); }
      .coaching-card.medium { border-left-color: var(--vscode-statusBarItem-warningBackground, #cca700); }
      .coaching-card.paused { border-left-color: var(--vscode-descriptionForeground, #8888); opacity: 0.85; }
      .coaching-title { font-weight: 700; margin-bottom: 0.3em; }
      .coaching-body { font-size: 0.92em; opacity: 0.9; }
      .why { font-size: 0.88em; opacity: 0.75; margin-top: 0.4em; }
      .try { font-size: 0.88em; margin-top: 0.3em; font-weight: 600; }
      .actions { margin-top: 0.6em; }
      .actions a { margin-right: 1em; text-decoration: none; }
      .health-number { font-size: 1.8em; font-weight: 800; }
      .disclaimer { font-size: 0.78em; opacity: 0.55; margin-top: 0.3em; }
      .prompt-quote { font-style: italic; opacity: 0.8; border-left: 2px solid var(--vscode-widget-border, #4448);
                      padding-left: 0.6em; margin: 0.4em 0; }
      .dim-row { display: flex; gap: 0.5em; align-items: baseline; padding: 0.1em 0; font-size: 0.9em; }
      .dim-status { flex-shrink: 0; width: 5.5em; opacity: 0.75; }
      code.rewrite { display: block; white-space: pre-wrap; background: var(--vscode-textCodeBlock-background, #4442);
                     padding: 0.6em; border-radius: 4px; font-size: 0.88em; margin: 0.4em 0; }
    `;

    if (data.state === "connecting") {
      return `<!DOCTYPE html><html><head><style>${style}</style></head>
        <body><p>Connecting to the local Claude Code Coach service...</p></body></html>`;
    }

    if (data.state === "offline") {
      return `<!DOCTYPE html><html><head><style>${style}</style></head>
        <body>
          <div class="row"><span>Connection</span><span class="badge warn">Offline</span></div>
          <p class="empty">${escapeHtml(data.message ?? "Coach service is not running")}</p>
          <p>Start the Coach service — <code>python -m claude_code_coach.service</code>, or the
          desktop app — to connect.</p>
        </body></html>`;
    }

    const status = data.status!;
    const session = data.session!;

    return `<!DOCTYPE html><html><head><style>${style}</style></head>
      <body>
        <div class="row"><span>Connection</span><span class="badge ok">Ready</span></div>
        <div class="row"><span class="label">Workspace</span><span>${escapeHtml(
          data.workspaceFolder ?? status.project_root ?? "(none)",
        )}</span></div>

        <h2>Current Coaching</h2>
        ${this.renderCurrentCoaching(session, data.environment)}

        <h2>Prompt Inspection</h2>
        ${this.renderInspection(data.inspection, data.inspectionError)}

        <h2 id="session-section">Session</h2>
        ${this.renderSession(session)}

        <h2>Verification</h2>
        ${this.renderVerification(session)}

        <h2>Environment</h2>
        ${this.renderEnvironment(data.environment)}
      </body></html>`;
  }

  private renderCurrentCoaching(session: SessionResponse, environment?: EnvironmentResponse): string {
    if (!session.session) {
      return `<p class="empty">No runtime session observed for this workspace yet.</p>`;
    }
    // Section 1/2, Phase 4E (docs/SHARED_COACH_STATE.md §3/4): prefer the
    // backend's own primary-signal selection — the same computation
    // Desktop's Runtime page now leads with — falling back to this
    // extension's own pickPrimarySignal() only if an older/incompatible
    // service response omits the field (Step 21 compatibility).
    const primary =
      session.primary_signal !== undefined
        ? (session.primary_signal ?? undefined)
        : pickPrimarySignal(session.signals);
    const secondary = primary ? session.signals.filter((s) => s !== primary) : session.signals;

    // Section 10, Phase 4E: pausing is now the backend's shared
    // `coaching_paused` flag, not a local vscode.Memento value — so this
    // agrees with what Desktop and any other VS Code window show for the
    // same service. Pausing suppresses the *interruption*, never the
    // underlying evidence — the full signal list stays visible underneath,
    // just without the leading intervention card.
    if (session.coaching_paused) {
      return `
        <div class="coaching-card paused">
          <div class="coaching-title">⏸ Coaching paused</div>
          <div class="coaching-body">Session data collection continues as normal. Run
            "Claude Code Coach: Resume Coaching" from the Command Palette to re-enable
            coaching cards and notifications.</div>
        </div>
        ${
          session.signals.length > 0
            ? `<details style="margin-top:0.6em;"><summary style="cursor:pointer; opacity:0.7;">${session.signals.length} signal(s) observed while paused</summary>
            ${session.signals.map((s) => `<div class="row"><span>${escapeHtml(s.message)}</span><span class="label">${escapeHtml(s.level)}</span></div>`).join("")}
            </details>`
            : ""
        }
      `;
    }

    if (!primary) {
      return `<div class="coaching-card good">
        <div class="coaching-title">✓ No immediate coaching action</div>
        <div class="coaching-body">Your current workflow looks healthy.</div>
      </div>`;
    }
    const cls = primary.level === "high" ? "high" : primary.level === "medium" ? "medium" : "";
    return `
      <div class="coaching-card ${cls}">
        <div class="coaching-title">${primary.level === "high" ? "⚠" : primary.level === "medium" ? "⚠" : "•"} ${escapeHtml(primary.message)}</div>
        ${primary.what_happened ? `<div class="coaching-body">${escapeHtml(primary.what_happened)}</div>` : ""}
        ${primary.why_it_matters ? `<div class="why">${escapeHtml(primary.why_it_matters)}</div>` : ""}
        ${primary.try_instead ? `<div class="try">Consider: ${escapeHtml(primary.try_instead)}</div>` : ""}
        ${this.renderCoachingActions(primary, environment)}
      </div>
      ${
        secondary.length > 0
          ? `<details style="margin-top:0.6em;"><summary style="cursor:pointer; opacity:0.7;">${secondary.length} more signal(s)</summary>
          ${secondary.map((s) => `<div class="row"><span>${escapeHtml(s.message)}</span><span class="label">${escapeHtml(s.level)}</span></div>`).join("")}
          </details>`
          : ""
      }
    `;
  }

  /** Section 13: a next action for the primary coaching card, where one
   * genuinely applies — never a forced/meaningless button. Every action
   * opens something for the user to look at; none of them execute the
   * suggestion automatically. */
  private renderCoachingActions(signal: RuntimeSignal, environment?: EnvironmentResponse): string {
    const links: string[] = [];
    if (signal.kind === "broad_exploration") {
      links.push(`<a href="${commandUri("claudeCodeCoach.inspectPrompt")}">Inspect Prompt</a>`);
      links.push(`<a href="#session-section">View Session</a>`);
    } else if (
      signal.kind === "context_noisy" ||
      signal.kind === "context_growth" ||
      signal.kind === "verification_missing"
    ) {
      links.push(`<a href="#session-section">View Session</a>`);
    } else if (signal.kind === "skill_underused" && environment) {
      const skillName = signal.evidence && (signal.evidence as Record<string, unknown>).skill;
      const match =
        typeof skillName === "string" ? environment.skills.find((s) => s.name === skillName) : undefined;
      if (match) {
        links.push(`<a href="${commandUri("claudeCodeCoach.openSkillOrAgentPath", [match.path])}">View Skill</a>`);
      }
    }
    return links.length > 0 ? `<div class="actions">${links.join("")}</div>` : "";
  }

  private renderInspection(inspection?: PromptInspection, error?: string): string {
    if (error) {
      return `<p class="empty">Prompt inspection failed: ${escapeHtml(error)}</p>
        <div class="actions"><a href="${commandUri("claudeCodeCoach.inspectPrompt")}">Inspect Prompt</a></div>`;
    }
    if (!inspection) {
      return `<p class="empty">No prompt inspected yet this session.</p>
        <div class="actions"><a href="${commandUri("claudeCodeCoach.inspectPrompt")}">Inspect Prompt</a></div>`;
    }

    const { analysis, suggestion, approach } = inspection;
    const dims = Object.entries(analysis.dimensions)
      .filter(([, d]) => d.status !== "na")
      .map(
        ([name, d]) =>
          `<div class="dim-row"><span class="dim-status">${escapeHtml(d.status)}</span><span>${escapeHtml(name)}${
            d.detail ? ` — ${escapeHtml(d.detail)}` : ""
          }</span></div>`,
      )
      .join("");

    const rewriteBlock =
      suggestion.suggested_text !== null
        ? `<code class="rewrite">${escapeHtml(suggestion.suggested_text)}</code>
           <div class="actions"><a href="${commandUri("claudeCodeCoach.copySuggestedPrompt")}">Copy</a></div>`
        : `<p class="empty">No safe rewrite available.</p>`;

    const primaryRec = pickPrimaryRecommendation(approach.recommendations);
    const approachBlock = primaryRec
      ? this.renderRecommendation(primaryRec)
      : `<p class="empty">A normal Claude Code session/prompt looks appropriate here.</p>`;

    return `
      <div class="prompt-quote">"${escapeHtml(inspection.prompt)}"</div>

      <div class="row"><span class="label">Quality</span><span>${analysis.score} / 100 (${escapeHtml(analysis.rating)})</span></div>
      <div class="row"><span class="label">Task type</span><span>${escapeHtml(analysis.task_type)}</span></div>
      ${dims}
      ${
        analysis.warnings.length > 0
          ? `<div style="margin-top:0.4em;">${analysis.warnings.map((w) => `<div>⚠ ${escapeHtml(w)}</div>`).join("")}</div>`
          : ""
      }

      <h3 style="margin-top:1em; font-size:0.85em; opacity:0.75;">Suggested Prompt</h3>
      ${rewriteBlock}

      <h3 style="margin-top:1em; font-size:0.85em; opacity:0.75;">Approach</h3>
      ${approachBlock}

      <div class="actions" style="margin-top:0.8em;"><a href="${commandUri("claudeCodeCoach.inspectPrompt")}">Inspect a different prompt</a></div>
    `;
  }

  private renderRecommendation(rec: ApproachRecommendation): string {
    const cls = rec.level === "high" ? "high" : rec.level === "medium" ? "medium" : "";
    let openAction = "";
    if ((rec.kind === "skill_existing" || rec.kind === "agent_existing") && this.lastFetched?.environment) {
      const name = (rec.evidence.skill ?? rec.evidence.agent) as string | undefined;
      const list: SkillOrAgentInfo[] =
        rec.kind === "skill_existing" ? this.lastFetched.environment.skills : this.lastFetched.environment.agents;
      const match = name ? list.find((item) => item.name === name) : undefined;
      if (match) {
        openAction = `<div class="actions"><a href="${commandUri("claudeCodeCoach.openSkillOrAgentPath", [match.path])}">Open ${
          rec.kind === "skill_existing" ? "Skill" : "Agent"
        }</a></div>`;
      }
    }
    return `
      <div class="coaching-card ${cls}">
        <div class="coaching-title">${escapeHtml(rec.icon)} ${escapeHtml(rec.message)}</div>
        ${rec.why_it_matters ? `<div class="why">${escapeHtml(rec.why_it_matters)}</div>` : ""}
        ${rec.try_instead ? `<div class="try">Consider: ${escapeHtml(rec.try_instead)}</div>` : ""}
        ${openAction}
      </div>
    `;
  }

  private renderSession(session: SessionResponse): string {
    const summary = session.session;
    if (!summary) {
      return `<p class="empty">No runtime session observed for this workspace yet.</p>`;
    }
    const health = session.context_health;
    // Session Title (deterministic, locally derived — never AI-generated;
    // see claude_code_coach/runtime/session_title.py) is the primary,
    // human-readable label. The raw UUID stays available, just secondary —
    // shown in small print with the full id in a tooltip, never removed.
    const title = summary.title || "Untitled session";
    return `
      <div class="session-title" style="font-size:1.1em; font-weight:700; margin-bottom:0.3em;" title="Session ID: ${escapeHtml(
        summary.session_id,
      )}">${escapeHtml(title)}</div>
      <div class="row"><span class="label">Prompts</span><span>${summary.prompts}</span></div>
      <div class="row"><span class="label">Tool calls</span><span>${summary.tool_calls}</span></div>
      <div class="row"><span class="label">Edits</span><span>${summary.edits}</span></div>
      ${
        health !== null
          ? `<div class="row"><span class="label">Context health</span><span class="health-number" style="color:${healthColor(
              health,
            )};">${health}</span></div>
             <div class="disclaimer">Local coaching heuristic — not an official Anthropic metric.</div>`
          : ""
      }
      <div class="row" style="margin-top:0.5em;"><span class="label">Session ID</span><span
        class="disclaimer" style="opacity:0.8;" title="${escapeHtml(summary.session_id)}">${escapeHtml(
          summary.session_id,
        )}</span></div>
    `;
  }

  private renderVerification(session: SessionResponse): string {
    const sig = session.signals.find((s) => s.kind === "verification_missing" || s.kind === "verification_done");
    if (!sig) {
      return `<p class="empty">No verification evidence observed.</p>`;
    }
    if (sig.kind === "verification_done") {
      return `<div class="coaching-card good"><div class="coaching-title">✓ Verification evidence observed</div></div>`;
    }
    return `
      <p>No verification evidence observed.</p>
      ${sig.try_instead ? `<div class="try">Consider: ${escapeHtml(sig.try_instead)}</div>` : ""}
    `;
  }

  private renderEnvironment(environment?: EnvironmentResponse): string {
    if (!environment) {
      return `<p class="empty">Environment not scanned.</p>`;
    }
    return Object.entries(environment.counts)
      .map(([k, v]) => `<div class="row"><span class="label">${escapeHtml(k)}</span><span>${v}</span></div>`)
      .join("");
  }
}
