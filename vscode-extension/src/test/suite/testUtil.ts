import * as fs from "fs";
import * as http from "http";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";
import { CoachingStateStore } from "../../coachingState";

/**
 * Shared helpers for the extension test suite: an isolated fake home
 * directory (so tests never touch the real ~/.claude_code_coach) plus a
 * tiny mock HTTP server that answers the same JSON shapes the real Python
 * service (claude_code_coach/service/models.py) produces, so CoachClient
 * is exercised over a real HTTP round-trip end to end.
 */

export function useFakeHome(): { dir: string; restore: () => void } {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "coach-ext-test-"));
  const original = process.env.USERPROFILE;
  process.env.USERPROFILE = dir;
  process.env.HOME = dir;
  fs.mkdirSync(path.join(dir, ".claude_code_coach"), { recursive: true });
  return {
    dir,
    restore: () => {
      if (original !== undefined) {
        process.env.USERPROFILE = original;
      }
      fs.rmSync(dir, { recursive: true, force: true });
    },
  };
}

export function appDirFor(fakeHomeDir: string): string {
  return path.join(fakeHomeDir, ".claude_code_coach");
}

export function writeServiceJson(
  fakeHomeDir: string,
  fields: Partial<{
    port: number; token: string; pid: number; started_at: string; api_version: string;
    schema_version: number; service_version: string;
  }>,
): void {
  const payload: Record<string, unknown> = {
    port: fields.port ?? 0,
    token: fields.token ?? "test-token",
    // Defaults to this test-runner process's own PID — always a live
    // process, so existing tests that don't care about Phase 4B's
    // stale-PID check (coachClient.ts's readDiscovery()) keep passing
    // unmodified. Pass an explicit dead PID (see a-pid-guaranteed-dead
    // below) to exercise that check specifically.
    pid: fields.pid ?? process.pid,
    started_at: fields.started_at ?? new Date().toISOString(),
    api_version: fields.api_version ?? "v1",
  };
  if (fields.schema_version !== undefined) {
    payload.schema_version = fields.schema_version;
  }
  if (fields.service_version !== undefined) {
    payload.service_version = fields.service_version;
  }
  fs.writeFileSync(
    path.join(appDirFor(fakeHomeDir), "service.json"),
    JSON.stringify(payload),
    "utf-8",
  );
}

/** A PID that is, by construction, never a real live process. Empirically
 * confirmed on this platform's Node runtime: `process.kill(-1, 0)` throws
 * ESRCH (unlike `process.kill(0, 0)`, which does NOT throw on Windows —
 * 0 has special meaning there, so it is deliberately not used here).
 * Avoids depending on OS PID-reuse timing the way "spawn a process and
 * wait for it to exit" would. Used by tests exercising the Phase 4B
 * stale-discovery-file path. */
export const A_PID_GUARANTEED_DEAD = -1;

/** A minimal in-memory stand-in for vscode.Memento (context.globalState),
 * used by coachingState.test.ts and coachPanel.test.ts so those suites
 * don't depend on a real extension context. */
export function makeFakeMemento(): vscode.Memento {
  const store = new Map<string, unknown>();
  return {
    get: ((key: string, defaultValue?: unknown) =>
      store.has(key) ? store.get(key) : defaultValue) as vscode.Memento["get"],
    update(key: string, value: unknown): Thenable<void> {
      store.set(key, value);
      return Promise.resolve();
    },
    keys(): readonly string[] {
      return [...store.keys()];
    },
  };
}

/** A fresh, not-paused CoachingStateStore backed by an in-memory fake
 * Memento — the default for panel tests that don't specifically exercise
 * pause/dedup behavior. */
export function makeCoachingState(): CoachingStateStore {
  return new CoachingStateStore(makeFakeMemento());
}

export interface MockService {
  port: number;
  token: string;
  server: http.Server;
  responses: Record<string, unknown>;
  postResponses: Record<string, (payload: unknown) => { status: number; body: unknown }>;
  close: () => Promise<void>;
}

/** Default POST handler for /analyze /suggest /approach: mirrors the real
 * server's "prompt must be a non-empty string" validation (400 with the
 * same error shape) so tests exercising error handling don't need custom
 * setup, but still returns real-shaped canned data for a valid prompt. */
function defaultPromptValidation(payload: unknown): string | null {
  const p = payload as { prompt?: unknown } | null;
  if (!p || typeof p.prompt !== "string" || !p.prompt.trim()) {
    return null;
  }
  return p.prompt;
}

/** A minimal stand-in for claude_code_coach/service/server.py — same
 * routes, same token-header check, same JSON shapes as models.py — so
 * CoachClient's HTTP layer is tested against a real listening socket. */
export function startMockService(): Promise<MockService> {
  const token = "mock-token-" + Math.random().toString(36).slice(2);

  const responses: Record<string, unknown> = {
    "/api/v1/health": { service: "claude-code-coach", api_version: "v1", status: "ready" },
    "/api/v1/status": {
      connected: true,
      runtime_configured: true,
      runtime_state: "live",
      project_root: "C:\\Projects\\Demo",
      last_event_at: "2026-01-01T00:00:00",
    },
    "/api/v1/session": {
      cwd: "C:\\Projects\\Demo",
      connection_state: "live",
      session: {
        session_id: "mock-session",
        title: "Fix Dashboard warning",
        started_at: "2026-01-01T00:00:00",
        last_event_at: "2026-01-01T00:05:00",
        prompts: 4,
        tool_calls: 6,
        searches: 1,
        reads: 2,
        edits: 3,
        commands: 0,
        skills_or_agents: 0,
        compactions: 0,
        ended: false,
      },
      context_health: 88,
      signals: [],
      // primary_signal deliberately omitted from this default mock (unlike
      // the real backend, which always includes it) so every existing test
      // that overrides only `signals` keeps exercising the Step 21
      // fallback path (pickPrimarySignal computed from `signals` locally)
      // exactly as before Phase 4E — see coachPanel.test.ts's dedicated
      // "primary_signal" suite for tests of the backend-preferred path.
      coaching_paused: false,
    },
    "/api/v1/environment": {
      project_root: "C:\\Projects\\Demo",
      scanned_at: "2026-01-01T00:00:00",
      counts: { skills: 1, agents: 0, claude_md: 1, mcp_servers: 0 },
      claude_md: [],
      skills: [],
      agents: [],
      mcp_servers: [],
      errors: [],
    },
  };

  const postResponses: Record<string, (payload: unknown) => { status: number; body: unknown }> = {
    "/api/v1/analyze": (payload) => {
      const prompt = defaultPromptValidation(payload);
      if (prompt === null) {
        return { status: 400, body: { error: "invalid_request", detail: "'prompt' must be a non-empty string" } };
      }
      return {
        status: 200,
        body: {
          prompt, task_type: "implementation", score: 42, rating: "NEEDS IMPROVEMENT",
          dimensions: { goal: { status: "missing", detail: "" } },
          good: [], warnings: ["Vague goal"], opportunities: [],
          breadth_level: 0, vague_goal: true, context_note: "",
        },
      };
    },
    "/api/v1/suggest": (payload) => {
      const prompt = defaultPromptValidation(payload);
      if (prompt === null) {
        return { status: 400, body: { error: "invalid_request", detail: "'prompt' must be a non-empty string" } };
      }
      return {
        status: 200,
        body: { category: "underspecified", message: "Could be sharper.", suggested_text: `Fix: ${prompt}` },
      };
    },
    "/api/v1/approach": (payload) => {
      const prompt = defaultPromptValidation(payload);
      if (prompt === null) {
        return { status: 400, body: { error: "invalid_request", detail: "'prompt' must be a non-empty string" } };
      }
      return {
        status: 200,
        body: {
          recommendations: [
            { kind: "normal_session", level: "low", icon: "•", message: "A normal session looks appropriate.",
              what_happened: "", why_it_matters: "", try_instead: "", evidence: {} },
          ],
        },
      };
    },
  };

  return new Promise((resolve) => {
    // `result.responses`/`result.postResponses` (not the local consts) are
    // what the handler reads on every request, so a test can swap either
    // out later (`mock.responses = {...}`) and have the very next request
    // see the change — used by the "refreshIfOpen picks up new data" test.
    const server = http.createServer((req, res) => {
      const url = new URL(req.url ?? "/", "http://127.0.0.1");
      const got = req.headers["x-coach-token"];

      if (req.method === "POST") {
        const handler = result.postResponses[url.pathname];
        if (!handler) {
          res.writeHead(404, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "not_found" }));
          return;
        }
        if (got !== token) {
          res.writeHead(401, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "unauthorized" }));
          return;
        }
        const chunks: Buffer[] = [];
        req.on("data", (c) => chunks.push(c));
        req.on("end", () => {
          let payload: unknown = {};
          try {
            payload = JSON.parse(Buffer.concat(chunks).toString("utf-8"));
          } catch {
            res.writeHead(400, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: "invalid_json" }));
            return;
          }
          const { status, body } = handler(payload);
          res.writeHead(status, { "Content-Type": "application/json" });
          res.end(JSON.stringify(body));
        });
        return;
      }

      const body = result.responses[url.pathname];
      if (got !== token) {
        res.writeHead(401, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "unauthorized" }));
        return;
      }
      if (!body) {
        res.writeHead(404, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "not_found" }));
        return;
      }
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(body));
    });
    const result: MockService = {
      port: 0,
      token,
      server,
      responses,
      postResponses,
      close: () => new Promise((res) => server.close(() => res())),
    };
    // Phase 4E: mirrors the real /api/v1/pause handler's effect on
    // /api/v1/session's coaching_paused field, so a test can pause/resume
    // through the mock service and observe the change on the next
    // session() call — same as the real Coach service's shared coach.db.
    // Added here (not in the `postResponses` literal above) because it
    // needs to read/replace `result.responses` — the live object every
    // request reads, including one already swapped out by a test.
    result.postResponses["/api/v1/pause"] = (payload) => {
      const p = payload as { paused?: unknown } | null;
      if (!p || typeof p.paused !== "boolean") {
        return { status: 400, body: { error: "invalid_request", detail: "'paused' must be a boolean" } };
      }
      const sessionResponse = result.responses["/api/v1/session"] as Record<string, unknown>;
      result.responses = {
        ...result.responses,
        "/api/v1/session": { ...sessionResponse, coaching_paused: p.paused },
      };
      return { status: 200, body: { coaching_paused: p.paused } };
    };
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      result.port = typeof address === "object" && address ? address.port : 0;
      resolve(result);
    });
  });
}
