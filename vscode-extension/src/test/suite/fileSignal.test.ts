import * as assert from "assert";
import * as fs from "fs";
import * as path from "path";
import { FileSignalWatcher } from "../../fileSignal";
import { appDirFor, useFakeHome } from "./testUtil";

suite("Signal file watcher", () => {
  test("fires onDidChange when vscode_signal.txt is created", async function () {
    this.timeout(15000);
    const fake = useFakeHome();
    const watcher = new FileSignalWatcher();
    try {
      watcher.start();
      const fired = new Promise<void>((resolve) => {
        watcher.onDidChange(() => resolve());
      });

      const signalPath = path.join(appDirFor(fake.dir), "vscode_signal.txt");
      // Give the watcher a beat to fully register before writing.
      await new Promise((r) => setTimeout(r, 300));
      fs.writeFileSync(signalPath, "runtime_event 2026-01-01T00:00:00 1", "utf-8");

      await Promise.race([
        fired,
        new Promise((_, reject) => setTimeout(() => reject(new Error("timed out waiting for signal")), 10000)),
      ]);
    } finally {
      watcher.dispose();
      fake.restore();
    }
  });

  test("start() does not throw when the app directory does not exist yet", () => {
    const fake = useFakeHome();
    fs.rmSync(appDirFor(fake.dir), { recursive: true, force: true });
    const watcher = new FileSignalWatcher();
    try {
      assert.doesNotThrow(() => watcher.start());
    } finally {
      watcher.dispose();
      fake.restore();
    }
  });
});
