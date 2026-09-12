import * as assert from "assert";
import { CoachClient, InvalidRequestError, getLastDiscoveryIssue, readDiscovery, ServiceUnavailableError } from "../../coachClient";
import { A_PID_GUARANTEED_DEAD, MockService, startMockService, useFakeHome, writeServiceJson } from "./testUtil";

suite("Service discovery", () => {
  test("readDiscovery returns null when service.json is absent", () => {
    const fake = useFakeHome();
    try {
      assert.strictEqual(readDiscovery(), null);
    } finally {
      fake.restore();
    }
  });

  test("readDiscovery returns null on malformed JSON rather than throwing", () => {
    const fake = useFakeHome();
    try {
      const fs = require("fs") as typeof import("fs");
      const path = require("path") as typeof import("path");
      fs.writeFileSync(
        path.join(fake.dir, ".claude_code_coach", "service.json"),
        "{not valid json",
        "utf-8",
      );
      assert.strictEqual(readDiscovery(), null);
    } finally {
      fake.restore();
    }
  });

  test("readDiscovery parses a well-formed service.json", () => {
    const fake = useFakeHome();
    try {
      writeServiceJson(fake.dir, { port: 12345, token: "abc" });
      const discovery = readDiscovery();
      assert.ok(discovery);
      assert.strictEqual(discovery!.port, 12345);
      assert.strictEqual(discovery!.token, "abc");
      assert.strictEqual(discovery!.api_version, "v1");
      assert.strictEqual(getLastDiscoveryIssue(), null);
    } finally {
      fake.restore();
    }
  });

  test("readDiscovery accepts a service.json without schema_version/service_version (older service)", () => {
    // Phase 4A added these fields additively — an already-running service
    // that hasn't been restarted since the upgrade, or any future service
    // that simply omits them, must never be rejected for their absence.
    const fake = useFakeHome();
    try {
      writeServiceJson(fake.dir, { port: 12345, token: "abc" });
      const discovery = readDiscovery();
      assert.ok(discovery);
      assert.strictEqual(discovery!.schema_version, undefined);
    } finally {
      fake.restore();
    }
  });

  test("readDiscovery accepts the Phase 4A schema_version/service_version fields when present", () => {
    const fake = useFakeHome();
    try {
      writeServiceJson(fake.dir, { port: 12345, token: "abc", schema_version: 1, service_version: "3.0.0" });
      const discovery = readDiscovery();
      assert.ok(discovery);
      assert.strictEqual(discovery!.schema_version, 1);
      assert.strictEqual(discovery!.service_version, "3.0.0");
    } finally {
      fake.restore();
    }
  });
});

suite("Phase 4B: discovery-file staleness and version compatibility (Step 3/4)", () => {
  test("a service.json pointing to a dead PID is treated as offline, not Ready", () => {
    const fake = useFakeHome();
    try {
      writeServiceJson(fake.dir, { port: 12345, token: "abc", pid: A_PID_GUARANTEED_DEAD });
      assert.strictEqual(readDiscovery(), null, "a stale discovery file must never be trusted");
      assert.match(
        getLastDiscoveryIssue() ?? "",
        /stale/i,
        "the diagnostic must say why, not just that it failed",
      );
    } finally {
      fake.restore();
    }
  });

  test("a service.json pointing to this test process's own (live) PID is trusted", () => {
    // The default writeServiceJson() pid (process.pid) already covers this
    // implicitly in every other test — asserted explicitly here as the
    // direct counterpart to the dead-PID case above.
    const fake = useFakeHome();
    try {
      writeServiceJson(fake.dir, { port: 12345, token: "abc" }); // pid defaults to process.pid
      assert.ok(readDiscovery());
      assert.strictEqual(getLastDiscoveryIssue(), null);
    } finally {
      fake.restore();
    }
  });

  test("an unrecognized api_version is reported as incompatible, distinct from plain offline", () => {
    const fake = useFakeHome();
    try {
      writeServiceJson(fake.dir, { port: 12345, token: "abc", api_version: "v2" });
      assert.strictEqual(readDiscovery(), null);
      assert.match(getLastDiscoveryIssue() ?? "", /incompatible/i);
      assert.match(getLastDiscoveryIssue() ?? "", /v2/);
    } finally {
      fake.restore();
    }
  });

  test("a missing service.json clears any previous diagnostic (routine offline, not a specific error)", () => {
    const fake = useFakeHome();
    try {
      // Establish a specific diagnostic first...
      writeServiceJson(fake.dir, { port: 12345, token: "abc", pid: A_PID_GUARANTEED_DEAD });
      readDiscovery();
      assert.ok(getLastDiscoveryIssue());

      // ...then remove the file entirely: this must read as the routine
      // "nothing has run yet" state, not a stale leftover diagnostic from
      // the previous call.
      const fs = require("fs") as typeof import("fs");
      const path = require("path") as typeof import("path");
      fs.rmSync(path.join(fake.dir, ".claude_code_coach", "service.json"), { force: true });
      assert.strictEqual(readDiscovery(), null);
      assert.strictEqual(getLastDiscoveryIssue(), null);
    } finally {
      fake.restore();
    }
  });

  test("CoachClient surfaces the specific diagnostic via ServiceUnavailableError's message", async () => {
    const fake = useFakeHome();
    try {
      writeServiceJson(fake.dir, { port: 12345, token: "abc", pid: A_PID_GUARANTEED_DEAD });
      const client = new CoachClient();
      await assert.rejects(() => client.health(), (err: unknown) => {
        assert.ok(err instanceof ServiceUnavailableError);
        assert.match((err as Error).message, /stale/i);
        return true;
      });
    } finally {
      fake.restore();
    }
  });
});

suite("CoachClient against a real listening service", () => {
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

  test("health check succeeds against a real socket", async () => {
    const client = new CoachClient();
    const health = await client.health();
    assert.strictEqual(health.status, "ready");
    assert.strictEqual(health.api_version, "v1");
  });

  test("status reflects a real HTTP response (connected state)", async () => {
    const client = new CoachClient();
    const status = await client.status();
    assert.strictEqual(status.connected, true);
    assert.strictEqual(status.runtime_configured, true);
  });

  test("session reflects a real HTTP response with session data", async () => {
    const client = new CoachClient();
    const session = await client.session("C:\\Projects\\Demo");
    assert.ok(session.session);
    assert.strictEqual(session.session!.session_id, "mock-session");
    assert.strictEqual(session.session!.prompts, 4);
  });

  test("wrong token is rejected (offline-equivalent failure)", async () => {
    writeServiceJson(fake.dir, { port: mock.port, token: "wrong-token" });
    const client = new CoachClient();
    await assert.rejects(() => client.health(), ServiceUnavailableError);
  });

  test("call throws ServiceUnavailableError when service.json is removed (offline state)", async () => {
    const fs = require("fs") as typeof import("fs");
    const path = require("path") as typeof import("path");
    fs.rmSync(path.join(fake.dir, ".claude_code_coach", "service.json"), { force: true });
    const client = new CoachClient();
    await assert.rejects(() => client.health(), ServiceUnavailableError);
  });

  test("reconnection: client recovers automatically once service.json returns", async () => {
    const fs = require("fs") as typeof import("fs");
    const path = require("path") as typeof import("path");
    const serviceJsonPath = path.join(fake.dir, ".claude_code_coach", "service.json");

    fs.rmSync(serviceJsonPath, { force: true });
    const client = new CoachClient();
    await assert.rejects(() => client.health(), ServiceUnavailableError);

    // Desktop app "restarts": service.json reappears, possibly with a new
    // port/token — the client must pick it up on the very next call with
    // no restart of the extension itself.
    writeServiceJson(fake.dir, { port: mock.port, token: mock.token });
    const health = await client.health();
    assert.strictEqual(health.status, "ready");
  });
});

suite("Phase 3: analyze / suggest / approach", () => {
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

  test("analyze() returns real analyzer output for a valid prompt", async () => {
    const client = new CoachClient();
    const result = await client.analyze("fix it");
    assert.strictEqual(result.prompt, "fix it");
    assert.strictEqual(typeof result.score, "number");
    assert.ok(result.dimensions.goal);
  });

  test("analyze() rejects with InvalidRequestError on empty prompt", async () => {
    const client = new CoachClient();
    await assert.rejects(() => client.analyze(""), InvalidRequestError);
  });

  test("suggest() returns a suggestion shape, possibly with null suggested_text", async () => {
    const client = new CoachClient();
    const result = await client.suggest("fix it");
    assert.strictEqual(typeof result.category, "string");
    assert.ok("suggested_text" in result);
  });

  test("approach() returns recommendations for a valid prompt", async () => {
    const client = new CoachClient();
    const result = await client.approach("Investigate the bug.", { projectRoot: "C:\\Demo" });
    assert.ok(Array.isArray(result.recommendations));
    assert.ok(result.recommendations.length >= 1);
  });

  test("InvalidRequestError carries the real server-provided detail message", async () => {
    const client = new CoachClient();
    try {
      await client.suggest("   ");
      assert.fail("expected suggest() to reject");
    } catch (err) {
      assert.ok(err instanceof InvalidRequestError);
      assert.match((err as Error).message, /non-empty string/);
    }
  });
});

suite("Phase 4E: shared pause state", () => {
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

  test("session() reports not paused by default", async () => {
    const client = new CoachClient();
    const session = await client.session();
    assert.strictEqual(session.coaching_paused, false);
  });

  test("setPaused(true) is reflected on the next session() call", async () => {
    const client = new CoachClient();
    const result = await client.setPaused(true);
    assert.strictEqual(result.coaching_paused, true);

    const session = await client.session();
    assert.strictEqual(session.coaching_paused, true);
  });

  test("setPaused(false) resumes", async () => {
    const client = new CoachClient();
    await client.setPaused(true);
    const result = await client.setPaused(false);
    assert.strictEqual(result.coaching_paused, false);

    const session = await client.session();
    assert.strictEqual(session.coaching_paused, false);
  });

  test("setPaused() rejects with ServiceUnavailableError when offline", async () => {
    const fs = require("fs") as typeof import("fs");
    const path = require("path") as typeof import("path");
    fs.rmSync(path.join(fake.dir, ".claude_code_coach", "service.json"), { force: true });
    const client = new CoachClient();
    await assert.rejects(() => client.setPaused(true), ServiceUnavailableError);
  });
});

suite("Client is offline-safe with nothing listening", () => {
  test("connection refused surfaces as ServiceUnavailableError, not a crash", async () => {
    const fake = useFakeHome();
    try {
      // Port 1 is a real, valid port number but nothing will be listening.
      writeServiceJson(fake.dir, { port: 1, token: "x" });
      const client = new CoachClient();
      await assert.rejects(() => client.health(), ServiceUnavailableError);
    } finally {
      fake.restore();
    }
  });
});
