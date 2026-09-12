/**
 * TypeScript mirrors of the JSON contracts produced by
 * claude_code_coach/service/models.py. Kept intentionally narrow — only the
 * fields the Phase 2 MVP panel/status bar actually reads are required;
 * everything else is optional so an older/newer service version never
 * crashes the extension on an unrecognized shape.
 */

export interface ServiceDiscovery {
  port: number;
  token: string;
  pid: number;
  started_at: string;
  api_version: string;
  // Phase 4A additions on the Python side (claude_code_coach/service/
  // lifecycle.py). Optional: an older already-running service (unlikely,
  // but not impossible mid-upgrade) won't have written these, and that
  // must never be treated as a parse failure.
  schema_version?: number;
  service_version?: string;
}

export interface HealthResponse {
  service: string;
  api_version: string;
  status: string;
}

export interface StatusResponse {
  connected: boolean;
  runtime_configured: boolean;
  runtime_state: string;
  project_root: string | null;
  last_event_at: string | null;
}

export interface SessionSummary {
  session_id: string;
  // Deterministic, locally-derived label (see claude_code_coach/runtime/
  // session_title.py) — never AI-generated. Optional so an older service
  // that predates this field never fails to parse.
  title?: string;
  started_at: string;
  last_event_at: string;
  prompts: number;
  tool_calls: number;
  searches: number;
  reads: number;
  edits: number;
  commands: number;
  skills_or_agents: number;
  compactions: number;
  ended: boolean;
}

export interface RuntimeSignal {
  kind: string;
  level: string;
  message: string;
  what_happened?: string;
  why_it_matters?: string;
  try_instead?: string;
  evidence?: unknown;
}

export interface SessionResponse {
  cwd: string | null;
  connection_state: string;
  session: SessionSummary | null;
  context_health: number | null;
  signals: RuntimeSignal[];
  // Phase 4E (docs/SHARED_COACH_STATE.md): backend-computed, shared across
  // every client of the same Coach service. Optional so an older service
  // that predates these fields still parses — see coaching.ts's fallback
  // logic and extension.ts's default-to-false/undefined handling.
  primary_signal?: RuntimeSignal | null;
  coaching_paused?: boolean;
}

export interface SkillOrAgentInfo {
  name: string;
  path: string;
  description: string;
  source: string;
  modified: string;
}

export interface EnvironmentResponse {
  project_root: string | null;
  scanned_at: string;
  counts: Record<string, number>;
  claude_md: unknown[];
  skills: SkillOrAgentInfo[];
  agents: SkillOrAgentInfo[];
  mcp_servers: unknown[];
  errors: string[];
}

/** Real, observed connection states only — never a fabricated/demo value.
 * "attention" (Phase 3B) is shown only when a MEDIUM- or HIGH-tier
 * RuntimeSignal is the current primary signal for this workspace's
 * session — never for a LOW-level/positive runtime event. See
 * coaching.ts's deriveCoachStatus(), the single source of truth shared by
 * the status bar, panel, and notification path. */
export type ConnectionStatus = "connecting" | "ready" | "offline" | "paused" | "attention";

// ---------------------------------------------------------------------------
// Phase 3: Prompt Inspector / Suggested Prompt / Approach Advisor.
// Mirrors claude_code_coach/service/models.py's Phase 3 additions exactly —
// every field here is real V5 output, never computed or guessed in TS.

export interface DimensionResult {
  status: "clear" | "partial" | "missing" | "na";
  detail: string;
}

export interface Opportunity {
  kind: string;
  message: string;
  confidence: "low" | "medium" | "high";
  reason: string;
}

export interface AnalysisResponse {
  prompt: string;
  task_type: string;
  score: number;
  rating: string;
  dimensions: Record<string, DimensionResult>;
  good: string[];
  warnings: string[];
  opportunities: Opportunity[];
  breadth_level: number;
  vague_goal: boolean;
  context_note: string;
}

export interface SuggestionResponse {
  category: string;
  message: string;
  suggested_text: string | null;
}

export interface ApproachRecommendation {
  kind: string;
  level: "low" | "medium" | "high";
  icon: string;
  message: string;
  what_happened: string;
  why_it_matters: string;
  try_instead: string;
  evidence: Record<string, unknown>;
}

export interface ApproachResponse {
  recommendations: ApproachRecommendation[];
}

/** The result of one "Inspect Prompt" run, bundled for the panel. */
export interface PromptInspection {
  prompt: string;
  analysis: AnalysisResponse;
  suggestion: SuggestionResponse;
  approach: ApproachResponse;
}
