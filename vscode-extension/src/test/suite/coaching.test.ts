import * as assert from "assert";
import {
  deriveCoachStatus,
  isActionableSignal,
  notificationMessage,
  pickPrimarySignal,
  shouldNotify,
  signalTier,
} from "../../coaching";
import { RuntimeSignal } from "../../types";

function signal(level: string, kind = "some_kind", message = "A coaching message."): RuntimeSignal {
  return { kind, level, message, what_happened: "", why_it_matters: "", try_instead: "", evidence: {} };
}

suite("Signal priority — high beats medium beats low", () => {
  test("no signals -> no primary", () => {
    assert.strictEqual(pickPrimarySignal([]), undefined);
  });

  test("a single low signal is still the primary when nothing else exists", () => {
    const low = signal("low");
    assert.strictEqual(pickPrimarySignal([low]), low);
  });

  test("high beats medium and low regardless of array order", () => {
    const low = signal("low");
    const medium = signal("medium");
    const high = signal("high");
    assert.strictEqual(pickPrimarySignal([low, medium, high]), high);
    assert.strictEqual(pickPrimarySignal([high, medium, low]), high);
  });

  test("medium beats low when no high signal exists", () => {
    const low = signal("low");
    const medium = signal("medium");
    assert.strictEqual(pickPrimarySignal([low, medium]), medium);
  });

  test("never combines signals into a new overall score — picks one real signal, unmodified", () => {
    const high = signal("high", "broad_exploration", "Broad exploration detected");
    const picked = pickPrimarySignal([signal("low"), high, signal("medium")]);
    assert.strictEqual(picked, high);
    assert.strictEqual(picked?.message, "Broad exploration detected");
  });
});

suite("signalTier — mirrors V5's own level field, no new scoring", () => {
  test("maps high/medium/low straight through", () => {
    assert.strictEqual(signalTier(signal("high")), "high");
    assert.strictEqual(signalTier(signal("medium")), "medium");
    assert.strictEqual(signalTier(signal("low")), "low");
  });

  test("an unrecognized level value is never promoted to high or medium", () => {
    assert.strictEqual(signalTier(signal("something_unexpected")), "low");
  });
});

suite("notificationMessage — short, single-line, real V5 text only", () => {
  test("uses the signal's own message, prefixed with the extension name", () => {
    const msg = notificationMessage(signal("high", "broad_exploration", "Broad exploration detected for a narrow task."));
    assert.strictEqual(msg, "Claude Code Coach: ⚠ Broad exploration detected for a narrow task.");
  });

  test("never spans multiple lines", () => {
    const msg = notificationMessage(signal("high"));
    assert.ok(!msg.includes("\n"));
  });
});

suite("shouldNotify — deterministic notification eligibility (spec section 2)", () => {
  const base = { notificationsEnabled: true, notificationLevel: "highOnly" as const, paused: false, recentlyNotified: false };

  test("high + enabled + highOnly -> notify", () => {
    assert.strictEqual(shouldNotify(signal("high"), base), true);
  });

  test("medium + highOnly -> no notification by default", () => {
    assert.strictEqual(shouldNotify(signal("medium"), base), false);
  });

  test("medium + highAndMedium -> notify", () => {
    assert.strictEqual(shouldNotify(signal("medium"), { ...base, notificationLevel: "highAndMedium" }), true);
  });

  test("low/positive signals never notify, even at highAndMedium", () => {
    assert.strictEqual(shouldNotify(signal("low"), { ...base, notificationLevel: "highAndMedium" }), false);
  });

  test("notifications disabled -> never notify, even for a high signal", () => {
    assert.strictEqual(shouldNotify(signal("high"), { ...base, notificationsEnabled: false }), false);
  });

  test("paused -> never notify", () => {
    assert.strictEqual(shouldNotify(signal("high"), { ...base, paused: true }), false);
  });

  test("recently notified (deduped) -> no repeat notification", () => {
    assert.strictEqual(shouldNotify(signal("high"), { ...base, recentlyNotified: true }), false);
  });

  test("notificationLevel 'off' suppresses even a high signal", () => {
    assert.strictEqual(shouldNotify(signal("high"), { ...base, notificationLevel: "off" }), false);
  });
});

suite("isActionableSignal — medium and high are actionable, low/positive are not", () => {
  test("high is actionable", () => {
    assert.strictEqual(isActionableSignal(signal("high")), true);
  });

  test("medium is actionable", () => {
    assert.strictEqual(isActionableSignal(signal("medium", "verification_missing")), true);
  });

  test("low is not actionable", () => {
    assert.strictEqual(isActionableSignal(signal("low")), false);
  });

  test("an unrecognized level is not actionable (mirrors signalTier's low fallback)", () => {
    assert.strictEqual(isActionableSignal(signal("something_unexpected")), false);
  });
});

/**
 * Phase 3B bugfix regression suite: the status bar previously stayed
 * "Ready" for a MEDIUM primary signal (e.g. verification_missing) even
 * though the panel showed a warning card and a native notification could
 * fire — see docs/VSCODE_INTEGRATION.md and the bug report this fixes.
 * deriveCoachStatus() is now the single function extension.ts calls to set
 * the status bar, so these cases are exactly the ones listed in the bug
 * report's "State selection" checklist.
 */
suite("deriveCoachStatus — single source of truth for the status bar (Phase 3B bugfix)", () => {
  test("no signal -> ready", () => {
    assert.strictEqual(deriveCoachStatus({ reachable: true, paused: false, primary: undefined }), "ready");
  });

  test("low signal -> ready", () => {
    assert.strictEqual(deriveCoachStatus({ reachable: true, paused: false, primary: signal("low") }), "ready");
  });

  test("medium actionable signal -> attention (this was the reported bug)", () => {
    const primary = signal(
      "medium",
      "verification_missing",
      "Implementation changed but no verification activity was observed.",
    );
    assert.strictEqual(deriveCoachStatus({ reachable: true, paused: false, primary }), "attention");
  });

  test("high actionable signal -> attention", () => {
    assert.strictEqual(deriveCoachStatus({ reachable: true, paused: false, primary: signal("high") }), "attention");
  });

  test("positive signal (low tier) -> ready", () => {
    const primary = signal("low", "verification_done", "Tests were run after the change.");
    assert.strictEqual(deriveCoachStatus({ reachable: true, paused: false, primary }), "ready");
  });

  test("paused + an active signal -> paused, not attention", () => {
    const primary = signal("high");
    assert.strictEqual(deriveCoachStatus({ reachable: true, paused: true, primary }), "paused");
  });

  test("offline + an active signal -> offline, not attention", () => {
    const primary = signal("high");
    assert.strictEqual(deriveCoachStatus({ reachable: false, paused: false, primary }), "offline");
  });

  test("offline takes precedence over paused too", () => {
    assert.strictEqual(deriveCoachStatus({ reachable: false, paused: true, primary: undefined }), "offline");
  });
});

suite("Notification eligibility is independent of Attention state (Phase 3B)", () => {
  const base = {
    notificationsEnabled: true,
    notificationLevel: "highAndMedium" as const,
    paused: false,
    recentlyNotified: false,
  };

  test("medium + highAndMedium -> notifies, and status is Attention", () => {
    const sig = signal("medium", "verification_missing", "Implementation changed but no verification activity was observed.");
    assert.strictEqual(shouldNotify(sig, base), true);
    assert.strictEqual(deriveCoachStatus({ reachable: true, paused: false, primary: sig }), "attention");
  });

  test("medium + highOnly -> no notification, but status is still Attention", () => {
    const sig = signal("medium", "verification_missing");
    assert.strictEqual(shouldNotify(sig, { ...base, notificationLevel: "highOnly" }), false);
    assert.strictEqual(deriveCoachStatus({ reachable: true, paused: false, primary: sig }), "attention");
  });

  test("deduped medium -> no repeat notification, but status remains Attention", () => {
    const sig = signal("medium", "verification_missing");
    assert.strictEqual(shouldNotify(sig, { ...base, recentlyNotified: true }), false);
    assert.strictEqual(deriveCoachStatus({ reachable: true, paused: false, primary: sig }), "attention");
  });

  test("paused + high -> no notification (shouldNotify), and status is Paused (not Attention)", () => {
    const sig = signal("high");
    assert.strictEqual(shouldNotify(sig, { ...base, paused: true }), false);
    assert.strictEqual(deriveCoachStatus({ reachable: true, paused: true, primary: sig }), "paused");
  });

  test("offline -> status is Offline regardless of any signal", () => {
    const sig = signal("high");
    assert.strictEqual(deriveCoachStatus({ reachable: false, paused: false, primary: sig }), "offline");
  });
});

/**
 * Confirms the panel (via pickPrimarySignal, exactly as coachPanel.ts's
 * renderCurrentCoaching() calls it) and the status bar (via
 * deriveCoachStatus) can never disagree, because both are driven from the
 * very same primary signal for the same /session payload.
 */
suite("Panel/status-bar agreement — same primary signal drives both (Phase 3B bugfix)", () => {
  test("verification_missing (MEDIUM) is the panel's primary signal AND drives status-bar Attention", () => {
    const signals = [
      signal("low", "search_first_good", "Good context discipline."),
      signal(
        "medium",
        "verification_missing",
        "Implementation changed but no verification activity was observed.",
      ),
    ];
    const primary = pickPrimarySignal(signals);
    assert.strictEqual(primary?.kind, "verification_missing");
    assert.strictEqual(deriveCoachStatus({ reachable: true, paused: false, primary }), "attention");
  });
});
