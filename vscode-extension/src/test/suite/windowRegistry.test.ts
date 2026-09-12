import * as assert from "assert";
import * as fs from "fs";
import * as path from "path";
import {
  listLiveWindowEntries,
  removeWindowRegistryEntry,
  writeWindowRegistryEntry,
} from "../../windowRegistry";
import { appDirFor, useFakeHome } from "./testUtil";

suite("Window registry — workspace identity", () => {
  test("writeWindowRegistryEntry writes a file named by this process's PID", () => {
    const fake = useFakeHome();
    try {
      writeWindowRegistryEntry();
      const file = path.join(appDirFor(fake.dir), "vscode_windows", `${process.pid}.json`);
      assert.ok(fs.existsSync(file), "registry entry file should exist");
      const entry = JSON.parse(fs.readFileSync(file, "utf-8"));
      assert.strictEqual(entry.pid, process.pid);
      assert.ok(Array.isArray(entry.folders));
      assert.ok(typeof entry.started_at === "string");
    } finally {
      removeWindowRegistryEntry();
      fake.restore();
    }
  });

  test("removeWindowRegistryEntry deletes this process's own file", () => {
    const fake = useFakeHome();
    try {
      writeWindowRegistryEntry();
      const file = path.join(appDirFor(fake.dir), "vscode_windows", `${process.pid}.json`);
      assert.ok(fs.existsSync(file));
      removeWindowRegistryEntry();
      assert.ok(!fs.existsSync(file));
    } finally {
      fake.restore();
    }
  });

  test("listLiveWindowEntries skips a stale PID that no longer exists", () => {
    const fake = useFakeHome();
    try {
      writeWindowRegistryEntry();
      const dir = path.join(appDirFor(fake.dir), "vscode_windows");
      // An implausible PID that (barring astronomical bad luck) is not a live process.
      fs.writeFileSync(
        path.join(dir, "999999.json"),
        JSON.stringify({ pid: 999999, folders: [], started_at: new Date().toISOString() }),
        "utf-8",
      );
      const live = listLiveWindowEntries();
      assert.ok(live.some((e) => e.pid === process.pid));
      assert.ok(!live.some((e) => e.pid === 999999));
    } finally {
      removeWindowRegistryEntry();
      fake.restore();
    }
  });

  test("listLiveWindowEntries returns an empty array when the registry dir doesn't exist", () => {
    const fake = useFakeHome();
    try {
      assert.deepStrictEqual(listLiveWindowEntries(), []);
    } finally {
      fake.restore();
    }
  });
});
