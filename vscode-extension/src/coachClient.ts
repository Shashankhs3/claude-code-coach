import * as fs from "fs";
import * as http from "http";
import * as os from "os";
import * as path from "path";
import {
  AnalysisResponse,
  ApproachResponse,
  EnvironmentResponse,
  HealthResponse,
  ServiceDiscovery,
  SessionResponse,
  StatusResponse,
  SuggestionResponse,
} from "./types";
import { isProcessAlive } from "./windowRegistry";

/**
 * Talks to exactly one place: 127.0.0.1, on the port/token published in
 * service.json by whichever claude_code_coach/service process is currently
 * running — the desktop app's embedded copy (app.py) or the standalone
 * `python -m claude_code_coach.service` process (Phase 4A). Both write the
 * identical discovery contract; this client has no way to (and no need to)
 * tell them apart. Never assumes a fixed port, never connects anywhere
 * else.
 */

/** api_version values this client can actually speak. A service reporting
 * anything else gets a specific "incompatible" diagnostic (Step 4) instead
 * of being silently treated as a routine "offline" — those are different
 * problems with different fixes. Additive/backward-compatible service
 * changes (e.g. new optional fields) never require a bump here — only a
 * genuine breaking change to the wire contract would. */
const SUPPORTED_API_VERSIONS = new Set(["v1"]);

/** Set by readDiscovery() on its most recent call — lets a caller (the
 * status bar / panel) show *why* the service looks unreachable (stale
 * discovery file vs. an incompatible service version) instead of a single
 * generic "Offline", without changing readDiscovery()'s own null-means-
 *-don't-connect contract that every existing caller already relies on. */
let lastDiscoveryIssue: string | null = null;

export function getLastDiscoveryIssue(): string | null {
  return lastDiscoveryIssue;
}

const REQUEST_TIMEOUT_MS = 4000;
// Prompt analysis can take a little longer than a plain status poll (a real
// environment scan runs as part of /approach) — generous but still bounded.
const PROMPT_REQUEST_TIMEOUT_MS = 10000;

/** A structurally invalid request (Phase 3 POST endpoints returning 400) —
 * distinct from ServiceUnavailableError so the UI can show the real
 * validation message instead of a generic "Coach Offline". */
export class InvalidRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidRequestError";
  }
}

export function appDir(): string {
  return path.join(os.homedir(), ".claude_code_coach");
}

export function serviceJsonPath(): string {
  return path.join(appDir(), "service.json");
}

export function signalFilePath(): string {
  return path.join(appDir(), "vscode_signal.txt");
}

export class ServiceUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ServiceUnavailableError";
  }
}

/** Reads and validates the discovery file. Returns null if no Coach
 * service is usable right now — file absent, malformed, pointing at a
 * dead process, or speaking an api_version this client doesn't
 * understand — rather than throwing. Plain "file absent" is an expected,
 * routine state; the other three are distinguishable via
 * getLastDiscoveryIssue() for a caller that wants to say more than
 * "Offline" (Step 4). Never trusts the file's mere presence — Step 3. */
export function readDiscovery(): ServiceDiscovery | null {
  let raw: string;
  try {
    raw = fs.readFileSync(serviceJsonPath(), "utf-8");
  } catch {
    lastDiscoveryIssue = null; // routine: no service has run yet, or none is running
    return null;
  }
  let parsed: Partial<ServiceDiscovery>;
  try {
    parsed = JSON.parse(raw) as Partial<ServiceDiscovery>;
  } catch {
    // service.json can be mid-write for a moment on startup/shutdown —
    // treat a parse failure the same as "not available yet", never crash.
    lastDiscoveryIssue = null;
    return null;
  }
  if (
    typeof parsed.port !== "number" ||
    typeof parsed.token !== "string" ||
    typeof parsed.api_version !== "string" ||
    typeof parsed.pid !== "number"
  ) {
    lastDiscoveryIssue = null; // malformed/mid-write — same routine treatment
    return null;
  }
  // Step 3: a discovery file's mere presence proves nothing — the process
  // that wrote it (desktop or standalone) may have been killed forcefully,
  // which skips the graceful cleanup that would otherwise remove this
  // file (see docs/STANDALONE_SERVICE.md). A dead PID means this is stale
  // data, not a reachable service.
  if (!isProcessAlive(parsed.pid)) {
    lastDiscoveryIssue = "Coach service discovery file is stale (the process that wrote it is no longer running).";
    return null;
  }
  // Step 4: an api_version this client doesn't recognize is a real,
  // specific problem — distinct from "nothing is running" — so it gets
  // its own diagnostic rather than being folded into plain Offline.
  if (!SUPPORTED_API_VERSIONS.has(parsed.api_version)) {
    lastDiscoveryIssue =
      `Coach service version is incompatible (service reports api_version ` +
      `"${parsed.api_version}", this extension supports ` +
      `${[...SUPPORTED_API_VERSIONS].join(", ")}). Update the extension or the Coach service.`;
    return null;
  }
  lastDiscoveryIssue = null;
  return parsed as ServiceDiscovery;
}

function request<T>(
  discovery: ServiceDiscovery,
  urlPath: string,
  options: { method?: "GET" | "POST"; body?: unknown; timeoutMs?: number } = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const bodyStr = options.body !== undefined ? JSON.stringify(options.body) : undefined;

  return new Promise((resolve, reject) => {
    const headers: Record<string, string> = { "X-Coach-Token": discovery.token };
    if (bodyStr !== undefined) {
      headers["Content-Type"] = "application/json";
      headers["Content-Length"] = String(Buffer.byteLength(bodyStr, "utf-8"));
    }
    const req = http.request(
      {
        host: "127.0.0.1",
        port: discovery.port,
        path: urlPath,
        method,
        headers,
        timeout: options.timeoutMs ?? REQUEST_TIMEOUT_MS,
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          const status = res.statusCode ?? 0;
          const body = Buffer.concat(chunks).toString("utf-8");

          if (status === 400) {
            let detail = "The Coach service rejected this request.";
            try {
              const parsed = JSON.parse(body) as { detail?: string; error?: string };
              detail = parsed.detail ?? parsed.error ?? detail;
            } catch {
              // fall through with the generic message
            }
            reject(new InvalidRequestError(detail));
            return;
          }
          if (status !== 200) {
            reject(new ServiceUnavailableError(`Coach service returned ${status}`));
            return;
          }
          try {
            resolve(JSON.parse(body) as T);
          } catch (e) {
            reject(new ServiceUnavailableError("Coach service returned invalid JSON"));
          }
        });
      },
    );
    req.on("timeout", () => {
      req.destroy();
      reject(new ServiceUnavailableError("Coach service request timed out"));
    });
    req.on("error", (err) => {
      reject(new ServiceUnavailableError(err.message));
    });
    if (bodyStr !== undefined) {
      req.write(bodyStr);
    }
    req.end();
  });
}

/**
 * Thin client: one method per read-only endpoint the Phase 2 service
 * exposes. Every call re-reads service.json first so any Coach service
 * restart (new port/token — desktop or standalone, Phase 4A) is picked up
 * automatically on the next call, with no extension restart required.
 */
export class CoachClient {
  private connect(): ServiceDiscovery {
    const discovery = readDiscovery();
    if (!discovery) {
      // getLastDiscoveryIssue() carries a specific diagnostic (stale
      // discovery file, incompatible api_version) when readDiscovery()
      // just set one; falls back to the generic message for the routine
      // "nothing has ever run" case. This is what lets the panel's offline
      // view (coachPanel.ts, via this error's .message) show the same
      // specific reason the status bar does.
      throw new ServiceUnavailableError(getLastDiscoveryIssue() ?? "Coach service is not running");
    }
    return discovery;
  }

  async health(): Promise<HealthResponse> {
    return request<HealthResponse>(this.connect(), "/api/v1/health");
  }

  async status(projectRoot?: string): Promise<StatusResponse> {
    const qs = projectRoot ? `?project_root=${encodeURIComponent(projectRoot)}` : "";
    return request<StatusResponse>(this.connect(), `/api/v1/status${qs}`);
  }

  async session(cwd?: string): Promise<SessionResponse> {
    const qs = cwd ? `?cwd=${encodeURIComponent(cwd)}` : "";
    return request<SessionResponse>(this.connect(), `/api/v1/session${qs}`);
  }

  /** Phase 4E (docs/SHARED_COACH_STATE.md §5): the one shared, mutable
   * piece of coaching state this extension changes remotely — it has no
   * direct coach.db access, unlike the desktop app. Shared automatically
   * with any other client (Desktop, another VS Code window) pointed at the
   * same standalone service, since both read the same coach.db setting.
   * Never stops hook event collection or the service itself — only
   * coaching interventions. */
  async setPaused(paused: boolean): Promise<{ coaching_paused: boolean }> {
    return request<{ coaching_paused: boolean }>(this.connect(), "/api/v1/pause", {
      method: "POST",
      body: { paused },
    });
  }

  async environment(projectRoot?: string): Promise<EnvironmentResponse> {
    const qs = projectRoot ? `?project_root=${encodeURIComponent(projectRoot)}` : "";
    return request<EnvironmentResponse>(this.connect(), `/api/v1/environment${qs}`);
  }

  /** Phase 3: real analyzer.analyze_prompt output for `prompt` — nothing
   * computed here, only forwarded. */
  async analyze(prompt: string): Promise<AnalysisResponse> {
    return request<AnalysisResponse>(this.connect(), "/api/v1/analyze", {
      method: "POST",
      body: { prompt },
      timeoutMs: PROMPT_REQUEST_TIMEOUT_MS,
    });
  }

  /** Phase 3: real prompt_rewriter.suggest_prompt output. suggested_text
   * may legitimately be null — the caller must render that as "no safe
   * rewrite available", never fabricate one. */
  async suggest(prompt: string): Promise<SuggestionResponse> {
    return request<SuggestionResponse>(this.connect(), "/api/v1/suggest", {
      method: "POST",
      body: { prompt },
      timeoutMs: PROMPT_REQUEST_TIMEOUT_MS,
    });
  }

  /** Phase 3: real integration.recommend_approach output, scoped to the
   * given workspace (project_root for environment, cwd for the runtime
   * session) exactly like /session and /environment already are. */
  async approach(prompt: string, opts: { projectRoot?: string; cwd?: string } = {}): Promise<ApproachResponse> {
    return request<ApproachResponse>(this.connect(), "/api/v1/approach", {
      method: "POST",
      body: { prompt, project_root: opts.projectRoot, cwd: opts.cwd },
      timeoutMs: PROMPT_REQUEST_TIMEOUT_MS,
    });
  }
}
