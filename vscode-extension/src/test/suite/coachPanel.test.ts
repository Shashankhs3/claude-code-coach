import * as assert from "assert";
import { CoachClient } from "../../coachClient";
import { CoachPanel } from "../../coachPanel";
import { makeCoachingState, MockService, startMockService, useFakeHome, writeServiceJson } from "./testUtil";

suite("Coach panel rendering (real HTTP response data)", () => {
  let mock: MockService;
  let fake: ReturnType<typeof useFakeHome>;

  setup(async () => {
    fake = useFakeHome();
    mock = await startMockService();
    writeServiceJson(fake.dir, { port: mock.port, token: mock.token });
  });

  teardown(async () => {
    await mock.close();
    fake.restore();
  });

  test("renders real Connection/Workspace/Runtime/Session data, not placeholders", async () => {
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      const html = panel.getHtmlForTests();

      assert.match(html, /Ready/);
      assert.match(html, /mock-session/, "the real session id from the mock service must appear");
      assert.match(html, /Fix Dashboard warning/, "the session title from the mock response must appear");
      assert.match(html, />4</, "prompts count (4) from the mock response must appear");
      assert.match(html, /88/, "context_health (88) from the mock response must appear");
      assert.doesNotMatch(html, /lorem ipsum/i);
    } finally {
      panel.dispose();
    }
  });

  test("UI stabilization: long values wrap instead of overflowing (Issues 6/8/19)", async () => {
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      const html = panel.getHtmlForTests();
      assert.match(html, /overflow-wrap:\s*anywhere/, "long paths/session IDs/messages must be able to wrap");
      assert.match(html, /\.row\s*>\s*\*\s*\{\s*min-width:\s*0/, "flex row children must be able to shrink below their content width");
    } finally {
      panel.dispose();
    }
  });

  test("falls back to 'Untitled session' when an older service omits title", async () => {
    const sessionResponse = mock.responses["/api/v1/session"] as Record<string, unknown>;
    const summary = { ...(sessionResponse.session as Record<string, unknown>) };
    delete summary.title;
    mock.responses = { ...mock.responses, "/api/v1/session": { ...sessionResponse, session: summary } };

    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      const html = panel.getHtmlForTests();
      assert.match(html, /Untitled session/);
      assert.match(html, /mock-session/, "the session id must still be shown as secondary info");
    } finally {
      panel.dispose();
    }
  });

  test("refreshIfOpen updates an already-open panel's content", async () => {
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      assert.match(panel.getHtmlForTests(), />4</);

      // Simulate a runtime event bumping prompts from 4 -> 9 between the
      // initial open and a later signal-triggered refresh.
      mock.responses = {
        ...mock.responses,
        "/api/v1/session": {
          ...(mock.responses["/api/v1/session"] as Record<string, unknown>),
          session: {
            ...((mock.responses["/api/v1/session"] as Record<string, unknown>).session as Record<
              string,
              unknown
            >),
            prompts: 9,
          },
        },
      };

      CoachPanel.refreshIfOpen(client);
      await new Promise((r) => setTimeout(r, 300));
      assert.match(panel.getHtmlForTests(), />9</);
    } finally {
      panel.dispose();
    }
  });

  test("refreshIfOpen is a no-op when no panel is open", () => {
    const client = new CoachClient();
    assert.doesNotThrow(() => CoachPanel.refreshIfOpen(client));
  });

  test("renders an Offline state when the service is unreachable", async () => {
    const fs = require("fs") as typeof import("fs");
    const path = require("path") as typeof import("path");
    fs.rmSync(path.join(fake.dir, ".claude_code_coach", "service.json"), { force: true });

    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      const html = panel.getHtmlForTests();
      assert.match(html, /Offline/);
    } finally {
      panel.dispose();
    }
  });
});

suite("Phase 3: Current Coaching signal priority", () => {
  let mock: MockService;
  let fake: ReturnType<typeof useFakeHome>;

  setup(async () => {
    fake = useFakeHome();
    mock = await startMockService();
    writeServiceJson(fake.dir, { port: mock.port, token: mock.token });
  });

  teardown(async () => {
    await mock.close();
    fake.restore();
  });

  test("shows 'No immediate coaching action' when there are no signals", async () => {
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      assert.match(panel.getHtmlForTests(), /No immediate coaching action/);
    } finally {
      panel.dispose();
    }
  });

  test("a real signal is never shown merely to fill space when none exists", async () => {
    // Sanity companion to the above: confirm no fabricated warning text
    // sneaks in when the mock legitimately reports zero signals.
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      assert.doesNotMatch(panel.getHtmlForTests(), /Broad exploration/);
    } finally {
      panel.dispose();
    }
  });

  test("picks the HIGH-level signal over a LOW-level one, using V5's own level field", async () => {
    const sessionResponse = mock.responses["/api/v1/session"] as Record<string, unknown>;
    mock.responses = {
      ...mock.responses,
      "/api/v1/session": {
        ...sessionResponse,
        signals: [
          { kind: "search_first_used", level: "low", message: "Good context discipline.",
            what_happened: "", why_it_matters: "", try_instead: "", evidence: {} },
          { kind: "context_noisy", level: "high", message: "Context is getting noisy.",
            what_happened: "Substantial activity accumulated.", why_it_matters: "Harder to reason about.",
            try_instead: "Compact the session or start fresh.", evidence: {} },
        ],
      },
    };
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      const html = panel.getHtmlForTests();
      assert.match(html, /Context is getting noisy/);
      assert.match(html, /Compact the session or start fresh/);
      assert.match(html, /1 more signal/);
    } finally {
      panel.dispose();
    }
  });
});

suite("Phase 3: Prompt Inspector / Suggested Prompt / Approach", () => {
  let mock: MockService;
  let fake: ReturnType<typeof useFakeHome>;

  setup(async () => {
    fake = useFakeHome();
    mock = await startMockService();
    writeServiceJson(fake.dir, { port: mock.port, token: mock.token });
  });

  teardown(async () => {
    await mock.close();
    fake.restore();
  });

  test("shows 'No prompt inspected yet' before any inspection runs", async () => {
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      assert.match(panel.getHtmlForTests(), /No prompt inspected yet/);
    } finally {
      panel.dispose();
    }
  });

  test("runInspection renders real analysis/suggestion/approach data", async () => {
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      await CoachPanel.runInspection(client, "fix it");
      const html = panel.getHtmlForTests();
      assert.match(html, /fix it/);
      assert.match(html, /NEEDS IMPROVEMENT/);
      assert.match(html, /Fix: fix it/); // the mock's suggested_text
    } finally {
      panel.dispose();
    }
  });

  test("shows 'No safe rewrite available' when suggested_text is null", async () => {
    mock.postResponses["/api/v1/suggest"] = () => ({
      status: 200,
      body: { category: "good", message: "Looks solid.", suggested_text: null },
    });
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      await CoachPanel.runInspection(client, "a well specified prompt");
      assert.match(panel.getHtmlForTests(), /No safe rewrite available/);
    } finally {
      panel.dispose();
    }
  });

  test("a detected Skill offers an Open Skill action with the real path", async () => {
    mock.responses = {
      ...mock.responses,
      "/api/v1/environment": {
        ...(mock.responses["/api/v1/environment"] as Record<string, unknown>),
        skills: [
          { name: "deploy-helper", path: "C:\\Skills\\deploy-helper\\SKILL.md",
            description: "", source: "project", modified: "2026-01-01" },
        ],
      },
    };
    mock.postResponses["/api/v1/approach"] = () => ({
      status: 200,
      body: {
        recommendations: [
          { kind: "skill_existing", level: "high", icon: "✓", message: "Use the existing Skill.",
            what_happened: "", why_it_matters: "", try_instead: "",
            evidence: { skill: "deploy-helper", confidence: "high" } },
        ],
      },
    });
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client); // populates environment before inspection renders it
      await CoachPanel.runInspection(client, "deploy the app");
      const html = panel.getHtmlForTests();
      assert.match(html, /Use the existing Skill/);
      assert.match(html, /Open Skill/);
      assert.match(html, /claudeCodeCoach\.openSkillOrAgentPath/);
    } finally {
      panel.dispose();
    }
  });

  test("an inspection error is shown, not a stale/fabricated result", async () => {
    mock.postResponses["/api/v1/analyze"] = () => ({
      status: 400, body: { error: "invalid_request", detail: "'prompt' must be a non-empty string" },
    });
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      await CoachPanel.runInspection(client, "x");
      assert.match(panel.getHtmlForTests(), /Prompt inspection failed/);
    } finally {
      panel.dispose();
    }
  });
});

suite("Phase 3: Verification section", () => {
  let mock: MockService;
  let fake: ReturnType<typeof useFakeHome>;

  setup(async () => {
    fake = useFakeHome();
    mock = await startMockService();
    writeServiceJson(fake.dir, { port: mock.port, token: mock.token });
  });

  teardown(async () => {
    await mock.close();
    fake.restore();
  });

  test("shows 'No verification evidence observed' with no verification signal", async () => {
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      assert.match(panel.getHtmlForTests(), /No verification evidence observed/);
    } finally {
      panel.dispose();
    }
  });

  test("shows 'Verification evidence observed' when V5 reports verification_done", async () => {
    mock.responses = {
      ...mock.responses,
      "/api/v1/session": {
        ...(mock.responses["/api/v1/session"] as Record<string, unknown>),
        signals: [
          { kind: "verification_done", level: "low", message: "Tests were run after the change.",
            what_happened: "", why_it_matters: "", try_instead: "", evidence: {} },
        ],
      },
    };
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      assert.match(panel.getHtmlForTests(), /Verification evidence observed/);
    } finally {
      panel.dispose();
    }
  });

  test("never claims the user 'didn't test' anything -- only V5's own wording", async () => {
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      assert.doesNotMatch(panel.getHtmlForTests(), /didn't test/i);
      assert.doesNotMatch(panel.getHtmlForTests(), /you failed to/i);
    } finally {
      panel.dispose();
    }
  });
});

suite("Phase 3B: Paused state (section 10)", () => {
  let mock: MockService;
  let fake: ReturnType<typeof useFakeHome>;

  setup(async () => {
    fake = useFakeHome();
    mock = await startMockService();
    writeServiceJson(fake.dir, { port: mock.port, token: mock.token });
  });

  teardown(async () => {
    await mock.close();
    fake.restore();
  });

  test("shows a paused notice instead of an intervention card when coaching is paused", async () => {
    // Phase 4E: pause is now the backend's own shared `coaching_paused`
    // field (docs/SHARED_COACH_STATE.md §5) — no longer a local
    // CoachingStateStore/vscode.Memento value, since Desktop or another VS
    // Code window may be the one that paused it.
    mock.responses = {
      ...mock.responses,
      "/api/v1/session": {
        ...(mock.responses["/api/v1/session"] as Record<string, unknown>),
        signals: [
          { kind: "context_noisy", level: "high", message: "Multiple unrelated tasks detected.",
            what_happened: "", why_it_matters: "", try_instead: "Start a fresh session.", evidence: {} },
        ],
        coaching_paused: true,
      },
    };

    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      const html = panel.getHtmlForTests();
      assert.match(html, /Coaching paused/);
      // The underlying evidence is not hidden, just not pushed as an
      // interruption — it stays available in the collapsible list.
      assert.match(html, /Multiple unrelated tasks detected/);
    } finally {
      panel.dispose();
    }
  });

  test("does not show a paused notice when coaching is active", async () => {
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      assert.doesNotMatch(panel.getHtmlForTests(), /Coaching paused/);
    } finally {
      panel.dispose();
    }
  });
});

suite("Phase 3B: Coaching action buttons (section 13)", () => {
  let mock: MockService;
  let fake: ReturnType<typeof useFakeHome>;

  setup(async () => {
    fake = useFakeHome();
    mock = await startMockService();
    writeServiceJson(fake.dir, { port: mock.port, token: mock.token });
  });

  teardown(async () => {
    await mock.close();
    fake.restore();
  });

  test("broad_exploration offers Inspect Prompt and View Session actions", async () => {
    mock.responses = {
      ...mock.responses,
      "/api/v1/session": {
        ...(mock.responses["/api/v1/session"] as Record<string, unknown>),
        signals: [
          { kind: "broad_exploration", level: "high", message: "Broad exploration detected.",
            what_happened: "", why_it_matters: "", try_instead: "Search first.", evidence: {} },
        ],
      },
    };
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      const html = panel.getHtmlForTests();
      assert.match(html, /claudeCodeCoach\.inspectPrompt/);
      assert.match(html, /href="#session-section"/);
      assert.match(html, /View Session/);
    } finally {
      panel.dispose();
    }
  });

  test("skill_underused with a resolvable skill offers a View Skill action with the real path", async () => {
    mock.responses = {
      ...mock.responses,
      "/api/v1/session": {
        ...(mock.responses["/api/v1/session"] as Record<string, unknown>),
        signals: [
          { kind: "skill_underused", level: "medium",
            message: "You have an existing Skill for this kind of work.",
            what_happened: "", why_it_matters: "", try_instead: "Use the Skill.",
            evidence: { skill: "deploy-helper" } },
        ],
      },
      "/api/v1/environment": {
        ...(mock.responses["/api/v1/environment"] as Record<string, unknown>),
        skills: [
          { name: "deploy-helper", path: "C:\\Skills\\deploy-helper\\SKILL.md",
            description: "", source: "project", modified: "2026-01-01" },
        ],
      },
    };
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      const html = panel.getHtmlForTests();
      assert.match(html, /View Skill/);
      assert.match(html, /claudeCodeCoach\.openSkillOrAgentPath/);
    } finally {
      panel.dispose();
    }
  });

  test("a signal kind with no defined action never shows a fabricated/meaningless button", async () => {
    mock.responses = {
      ...mock.responses,
      "/api/v1/session": {
        ...(mock.responses["/api/v1/session"] as Record<string, unknown>),
        signals: [
          { kind: "agent_delegation_opportunity", level: "low", message: "Multiple areas touched.",
            what_happened: "", why_it_matters: "", try_instead: "", evidence: {} },
        ],
      },
    };
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      const html = panel.getHtmlForTests();
      assert.doesNotMatch(html, /View Skill/);
      assert.doesNotMatch(html, /View Session/);
    } finally {
      panel.dispose();
    }
  });
});

suite("Phase 4E: backend-selected primary_signal (docs/SHARED_COACH_STATE.md §3/4)", () => {
  let mock: MockService;
  let fake: ReturnType<typeof useFakeHome>;

  setup(async () => {
    fake = useFakeHome();
    mock = await startMockService();
    writeServiceJson(fake.dir, { port: mock.port, token: mock.token });
  });

  teardown(async () => {
    await mock.close();
    fake.restore();
  });

  const lowSignal = {
    kind: "search_first_good", level: "low", message: "Good search-first pattern.",
    what_happened: "", why_it_matters: "", try_instead: "", evidence: {},
  };
  const highSignal = {
    kind: "verification_missing", level: "high", message: "No verification evidence observed.",
    what_happened: "", why_it_matters: "", try_instead: "Run the tests.", evidence: {},
  };

  test("uses the backend's own primary_signal even when it disagrees with local level-sorting order", async () => {
    // The backend is authoritative (§4) — the extension must render
    // whichever signal it names as primary_signal, not re-derive one.
    mock.responses = {
      ...mock.responses,
      "/api/v1/session": {
        ...(mock.responses["/api/v1/session"] as Record<string, unknown>),
        signals: [highSignal, lowSignal],
        primary_signal: lowSignal,
      },
    };
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      const html = panel.getHtmlForTests();
      assert.match(html, /Good search-first pattern/);
    } finally {
      panel.dispose();
    }
  });

  test("falls back to local pickPrimarySignal when an older service omits primary_signal", async () => {
    mock.responses = {
      ...mock.responses,
      "/api/v1/session": {
        ...(mock.responses["/api/v1/session"] as Record<string, unknown>),
        signals: [lowSignal, highSignal],
        // primary_signal deliberately absent — simulates a pre-4E service.
      },
    };
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      const html = panel.getHtmlForTests();
      assert.match(html, /No verification evidence observed/, "high must win the local level-sort fallback");
    } finally {
      panel.dispose();
    }
  });

  test("primary_signal: null (no signals) shows the healthy/no-action card, not a crash", async () => {
    mock.responses = {
      ...mock.responses,
      "/api/v1/session": {
        ...(mock.responses["/api/v1/session"] as Record<string, unknown>),
        signals: [],
        primary_signal: null,
      },
    };
    const client = new CoachClient();
    const panel = CoachPanel.createOrShow(client, makeCoachingState());
    try {
      await panel.refresh(client);
      const html = panel.getHtmlForTests();
      assert.match(html, /No immediate coaching action/);
    } finally {
      panel.dispose();
    }
  });
});
