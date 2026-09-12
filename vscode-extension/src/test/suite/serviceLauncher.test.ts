import * as assert from "assert";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { readDiscovery } from "../../coachClient";
import {
  claimStartingLock,
  ensureServiceRunning,
  releaseStartingLock,
  resetBackoffStateForTests,
  resolveBundledServicePath,
  spawnAndWaitForReady,
  waitForReady,
} from "../../serviceLauncher";
import { A_PID_GUARANTEED_DEAD, useFakeHome, writeServiceJson } from "./testUtil";

/** A short script for `node -e`, standing in for the real CoachService.exe
 * without needing one to have been built first: writes a real, well-formed
 * service.json (this test process's own PID, so readDiscovery()'s liveness
 * check passes) after `delayMs`, then just idles so the "service" looks
 * like a real running process for as long as the test needs it to. */
function fakeServiceScript(fakeHomeDir: string, delayMs: number): string {
  const servicePath = path.join(fakeHomeDir, ".claude_code_coach", "service.json").replace(/\\/g, "\\\\");
  return (
    `setTimeout(() => { require('fs').writeFileSync(${JSON.stringify(servicePath)}, JSON.stringify({` +
    `port: 1, token: "t", pid: process.pid, started_at: new Date().toISOString(), api_version: "v1"` +
    `})); }, ${delayMs}); setInterval(() => {}, 1000);`
  );
}

/** The real, actually-built CoachService.exe from
 * packaging/build_vscode_service.ps1, if this dev machine has run it —
 * used only by the one true end-to-end test below, which skips itself
 * rather than fail when this hasn't been built (Part 9: "perform a real
 * Windows startup test if the environment supports it" — conditional on
 * that support actually being there). */
function realBuiltServiceDir(): string | undefined {
  const dir = path.resolve(__dirname, "..", "..", "..", "..", "packaging", "build", "coachservice_dist", "CoachService");
  return fs.existsSync(path.join(dir, "CoachService.exe")) ? dir : undefined;
}

suite("serviceLauncher: path resolution", () => {
  test("resolveBundledServicePath returns undefined when nothing is bundled", () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "coach-ext-nobundle-"));
    try {
      assert.strictEqual(resolveBundledServicePath(tmp), undefined);
    } finally {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
  });

  test("resolveBundledServicePath finds a real file at the exact expected layout", function () {
    if (process.platform !== "win32" || process.arch !== "x64") {
      this.skip(); // pre-release scope is Windows x64 only — see the module docstring
    }
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "coach-ext-bundle-"));
    try {
      const exeDir = path.join(tmp, "bundled", "win32-x64", "CoachService");
      fs.mkdirSync(exeDir, { recursive: true });
      const exePath = path.join(exeDir, "CoachService.exe");
      fs.writeFileSync(exePath, "not a real exe, just needs to exist as a file");
      assert.strictEqual(resolveBundledServicePath(tmp), exePath);
    } finally {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
  });

  test("resolveBundledServicePath does not mistake a directory for the exe", () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "coach-ext-bundledir-"));
    try {
      // CoachService.exe exists as a directory, not a file — must not be
      // returned as a spawnable path.
      fs.mkdirSync(path.join(tmp, "bundled", "win32-x64", "CoachService", "CoachService.exe"), { recursive: true });
      assert.strictEqual(resolveBundledServicePath(tmp), undefined);
    } finally {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
  });
});

suite("serviceLauncher: starting lock (duplicate-start prevention)", () => {
  test("a second claim fails while the first is fresh", () => {
    const fake = useFakeHome();
    try {
      assert.strictEqual(claimStartingLock(5000), true);
      assert.strictEqual(claimStartingLock(5000), false);
    } finally {
      releaseStartingLock();
      fake.restore();
    }
  });

  test("release lets an immediate re-claim succeed", () => {
    const fake = useFakeHome();
    try {
      assert.strictEqual(claimStartingLock(5000), true);
      releaseStartingLock();
      assert.strictEqual(claimStartingLock(5000), true);
    } finally {
      releaseStartingLock();
      fake.restore();
    }
  });

  test("a lock older than its TTL is treated as abandoned and reclaimed", async () => {
    const fake = useFakeHome();
    try {
      assert.strictEqual(claimStartingLock(50), true);
      await new Promise((r) => setTimeout(r, 120));
      // Still present on disk from the first call, but that TTL (50ms)
      // has long since passed — a crashed/reloaded window's lock must
      // never permanently block every future attempt.
      assert.strictEqual(claimStartingLock(50), true);
    } finally {
      releaseStartingLock();
      fake.restore();
    }
  });
});

suite("serviceLauncher: spawn and wait for readiness", () => {
  test("readiness timeout: a process that never writes service.json resolves false, not hung", async () => {
    const fake = useFakeHome();
    try {
      const result = await spawnAndWaitForReady(process.execPath, ["-e", "setInterval(() => {}, 1000);"], 700);
      assert.strictEqual(result.ready, false);
    } finally {
      fake.restore();
    }
  }).timeout(5000);

  test("a process that writes a valid service.json shortly after starting is detected as ready", async () => {
    const fake = useFakeHome();
    try {
      const result = await spawnAndWaitForReady(process.execPath, ["-e", fakeServiceScript(fake.dir, 200)], 3000);
      assert.strictEqual(result.ready, true);
    } finally {
      fake.restore();
    }
  }).timeout(5000);

  test("never connects on process-alive alone: a running process that never becomes discoverable is not ready", async () => {
    // The process is genuinely running (spawn succeeds, no error) for the
    // entire wait — the only reason this must resolve false is that
    // readDiscovery() never validates anything, proving readiness is
    // decided by discovery, never by "did something start."
    const fake = useFakeHome();
    try {
      const result = await spawnAndWaitForReady(process.execPath, ["-e", "setInterval(() => {}, 1000);"], 500);
      assert.strictEqual(result.ready, false);
      assert.strictEqual(result.spawnError, undefined);
    } finally {
      fake.restore();
    }
  }).timeout(5000);

  test("waitForReady alone becomes true the moment a valid service.json appears", async () => {
    const fake = useFakeHome();
    try {
      const pending = waitForReady(3000, 50);
      setTimeout(() => writeServiceJson(fake.dir, { port: 1, token: "t" }), 150);
      assert.strictEqual(await pending, true);
    } finally {
      fake.restore();
    }
  }).timeout(5000);
});

suite("serviceLauncher: ensureServiceRunning", () => {
  setup(() => resetBackoffStateForTests());
  teardown(() => releaseStartingLock());

  test("existing service reuse: a valid discovery file means nothing is started", async () => {
    const fake = useFakeHome();
    try {
      writeServiceJson(fake.dir, { port: 12345, token: "abc" });
      const result = await ensureServiceRunning("/does/not/matter");
      assert.deepStrictEqual(result, { alreadyRunning: true, started: false });
    } finally {
      fake.restore();
    }
  });

  test("stale service recovery: a dead-PID discovery file is treated as not running, not as already running", async () => {
    const fake = useFakeHome();
    try {
      writeServiceJson(fake.dir, { port: 12345, token: "abc", pid: A_PID_GUARANTEED_DEAD });
      // No bundled exe at this path — proves the function actually moved
      // past "is something already running?" to "let's try to start one,"
      // rather than short-circuiting on the stale file's mere presence.
      const result = await ensureServiceRunning("/does/not/exist/anywhere");
      assert.strictEqual(result.alreadyRunning, false);
      assert.strictEqual(result.started, false);
      assert.strictEqual(result.reason, "no bundled Coach service for this platform");
    } finally {
      fake.restore();
    }
  });

  test("no bundled service for this platform/path is reported, never silently treated as success", async () => {
    const fake = useFakeHome();
    try {
      const result = await ensureServiceRunning("/does/not/exist/anywhere");
      assert.strictEqual(result.alreadyRunning, false);
      assert.strictEqual(result.started, false);
      assert.strictEqual(result.reason, "no bundled Coach service for this platform");
    } finally {
      fake.restore();
    }
  });

  test("real Windows startup test: the actually-built CoachService.exe starts and becomes discoverable", async function () {
    const realDir = realBuiltServiceDir();
    if (!realDir) {
      this.skip(); // run packaging\build_vscode_service.ps1 first to exercise this specific test
    }
    const fake = useFakeHome();
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "coach-ext-realexe-"));
    let spawnedPid: number | undefined;
    try {
      const bundledDst = path.join(tmp, "bundled", "win32-x64", "CoachService");
      fs.mkdirSync(path.dirname(bundledDst), { recursive: true });
      fs.cpSync(realDir!, bundledDst, { recursive: true });

      const result = await ensureServiceRunning(tmp);
      assert.strictEqual(result.started, true, result.reason);
      assert.strictEqual(result.alreadyRunning, false);

      const discovery = readDiscovery();
      assert.ok(discovery, "the real exe's own service.json must be discoverable after starting");
      spawnedPid = discovery!.pid;
    } finally {
      // This spawns a REAL, detached background process (by design — see
      // the module docstring's "Service lifetime" note) — a test must not
      // leave it running on the machine afterward.
      if (spawnedPid !== undefined) {
        try {
          process.kill(spawnedPid);
        } catch {
          // already gone — fine
        }
      }
      // Windows can hold the just-killed process's exe/DLL file handles
      // open for a brief moment after process.kill() returns — rmSync's
      // own built-in retry (maxRetries) is for ENOENT/transient races, not
      // this EPERM-while-a-handle-closes case, so retry here explicitly
      // rather than fail the whole test on cleanup after the real
      // assertions above already passed.
      for (let attempt = 0; attempt < 10; attempt++) {
        try {
          fs.rmSync(tmp, { recursive: true, force: true });
          break;
        } catch {
          await new Promise((r) => setTimeout(r, 200));
        }
      }
      fake.restore();
    }
  }).timeout(15000);
});
