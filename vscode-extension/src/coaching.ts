import { RuntimeSignal } from "./types";

/**
 * Phase 3B: the single deterministic "what should I lead with" selector,
 * shared by the panel (Current Coaching card) and the background
 * notification/status-bar path — previously duplicated as a private helper
 * inside coachPanel.ts. No new scoring system: this only sorts by V5's own
 * `level` field (high > medium > low), exactly as coachPanel.ts already did.
 */
const LEVEL_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };

export function pickPrimarySignal(signals: RuntimeSignal[]): RuntimeSignal | undefined {
  if (signals.length === 0) {
    return undefined;
  }
  return [...signals].sort((a, b) => (LEVEL_ORDER[a.level] ?? 9) - (LEVEL_ORDER[b.level] ?? 9))[0];
}

/** V5's `level` field *is* the product tier — HIGH/MEDIUM/LOW. No second,
 * combined "overall score" is ever computed here or anywhere else in the
 * extension. */
export type SignalTier = "high" | "medium" | "low";

export function signalTier(signal: RuntimeSignal): SignalTier {
  return signal.level === "high" ? "high" : signal.level === "medium" ? "medium" : "low";
}

/** Kinds V5 already uses for affirmative/good-practice signals (spec section
 * 7). Purely a rendering choice (✓ vs ⚠) — never a second severity axis;
 * every one of these is already `level: "low"`. */
const POSITIVE_KINDS = new Set(["search_first_good", "context_coherent", "verification_done"]);

export function isPositiveKind(kind: string): boolean {
  return POSITIVE_KINDS.has(kind);
}

/** Native-notification text (section 14): short, single-line, built only
 * from V5's own `message` field — never a paragraph, never fabricated. The
 * "Claude Code Coach: " prefix matches the convention already used for
 * other user-visible strings in this extension (see extension.ts's
 * status-bar confirmation and Inspect Prompt input box title). */
export function notificationMessage(signal: RuntimeSignal): string {
  return `Claude Code Coach: ⚠ ${signal.message}`;
}

/**
 * Phase 3B bugfix: previously the status bar only entered "attention" for a
 * HIGH-tier primary signal, while the panel (via pickPrimarySignal, above)
 * and the notification path already treated MEDIUM as an actionable
 * warning — so a MEDIUM signal like verification_missing showed a ⚠
 * warning card in the panel, and could fire a native notification, while
 * the status bar still said "Ready". Attention now means "there is an
 * active medium/high actionable primary signal", matching what the panel
 * already renders as a warning card (coachPanel.ts's cls/icon logic treats
 * medium and high identically). LOW/positive signals (see isPositiveKind)
 * are never Attention, exactly as they are never natively notified.
 */
export function isActionableSignal(signal: RuntimeSignal): boolean {
  return signalTier(signal) !== "low";
}

/** States the status bar can be in once the Coach service is confirmed
 * reachable and coaching isn't paused — i.e. driven purely by whether an
 * actionable signal is currently active. Excludes "connecting", which is
 * the extension's own just-activated state, never derived from a signal. */
export type CoachActivityState = "attention" | "ready";

function deriveCoachActivityState(primary: RuntimeSignal | undefined): CoachActivityState {
  return primary && isActionableSignal(primary) ? "attention" : "ready";
}

export type CoachStatus = "offline" | "paused" | CoachActivityState;

/**
 * The single deterministic "what should the status bar/panel/notification
 * path show right now" derivation (Phase 3B: "create one deterministic
 * current-coaching state" rather than letting each surface decide on its
 * own). Built on the same pickPrimarySignal() the panel already uses for
 * its Current Coaching card — a caller that computes `primary` once and
 * passes it here, to the panel, and to shouldNotify() can never have the
 * status bar and panel disagree about whether a coaching signal is active.
 *
 * Offline takes precedence over everything: a stale Attention/Ready must
 * never survive the Coach service becoming unreachable. Paused takes
 * precedence over any signal (section 10) — the *interruption* is
 * suppressed, never the underlying evidence, which the panel still lists
 * separately even while paused.
 */
export function deriveCoachStatus(input: {
  reachable: boolean;
  paused: boolean;
  primary: RuntimeSignal | undefined;
}): CoachStatus {
  if (!input.reachable) {
    return "offline";
  }
  if (input.paused) {
    return "paused";
  }
  return deriveCoachActivityState(input.primary);
}

export type NotificationLevelSetting = "highOnly" | "highAndMedium" | "off";

export interface NotificationDecisionInput {
  notificationsEnabled: boolean;
  notificationLevel: NotificationLevelSetting;
  paused: boolean;
  recentlyNotified: boolean;
}

/**
 * Deterministic notification-eligibility rule (spec section 2). Every
 * condition is checked independently so the truth table stays easy to
 * reason about and test:
 *   - paused, or notifications disabled outright -> never
 *   - LOW/positive signals -> never notify natively, regardless of settings
 *     (spec: "Do not generate native notifications for routine positive
 *     events") — not user-configurable, by design.
 *   - HIGH -> notify unless the user set notificationLevel to "off"
 *   - MEDIUM -> notify only if the user opted into "High + Medium"
 *   - a signal already shown recently for this exact (workspace, session,
 *     kind) -> never (deduplication; see coachingState.ts)
 *
 * Not to be confused with deriveCoachStatus()/isActionableSignal() above:
 * this function governs whether an *interruption* (a native toast) fires —
 * it is deliberately more restrictive, gated by the user's
 * notificationLevel preference and by dedup. Whether the signal is
 * *currently active* (what the status bar and panel show) is decided
 * separately by deriveCoachStatus, and is never reduced by these same
 * preference/dedup checks — a deduped or notificationLevel-suppressed
 * MEDIUM signal still shows the status bar as Attention as long as it
 * remains the primary signal.
 */
export function shouldNotify(signal: RuntimeSignal, input: NotificationDecisionInput): boolean {
  if (input.paused || !input.notificationsEnabled || input.recentlyNotified) {
    return false;
  }
  const tier = signalTier(signal);
  if (tier === "low") {
    return false;
  }
  if (tier === "high") {
    return input.notificationLevel !== "off";
  }
  return input.notificationLevel === "highAndMedium";
}
