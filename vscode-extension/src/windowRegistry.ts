import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { appDir } from "./coachClient";

/**
 * Forward-looking groundwork only (architecture doc §9) — mirrors the
 * confirmed singularityinc.claude-notifier pattern of one file per running
 * window, keyed by PID, under a registry directory. Nothing in Phase 2
 * reads this registry yet; it exists so a future feature (routing a
 * notification to the specific window that owns a session) doesn't need a
 * second pass. Written on activate(), removed on deactivate() — best
 * effort, never blocks extension startup/shutdown on failure.
 */

interface WindowRegistryEntry {
  pid: number;
  folders: string[];
  started_at: string;
}

function registryDir(): string {
  return path.join(appDir(), "vscode_windows");
}

function registryFilePath(): string {
  return path.join(registryDir(), `${process.pid}.json`);
}

export function writeWindowRegistryEntry(): void {
  try {
    fs.mkdirSync(registryDir(), { recursive: true });
    const entry: WindowRegistryEntry = {
      pid: process.pid,
      folders: (vscode.workspace.workspaceFolders ?? []).map((f) => f.uri.fsPath),
      started_at: new Date().toISOString(),
    };
    fs.writeFileSync(registryFilePath(), JSON.stringify(entry), "utf-8");
  } catch {
    // Best effort — this registry is not required for Phase 2 functionality.
  }
}

export function removeWindowRegistryEntry(): void {
  try {
    fs.rmSync(registryFilePath(), { force: true });
  } catch {
    // Best effort on shutdown too.
  }
}

/** Kept for parity with the architecture doc's stated future consumer —
 * unused in Phase 2, exported so it's exercised by a test rather than left
 * as dead, unverifiable code. */
export function listLiveWindowEntries(): WindowRegistryEntry[] {
  let files: string[];
  try {
    files = fs.readdirSync(registryDir());
  } catch {
    return [];
  }
  const entries: WindowRegistryEntry[] = [];
  for (const file of files) {
    try {
      const raw = fs.readFileSync(path.join(registryDir(), file), "utf-8");
      const parsed = JSON.parse(raw) as WindowRegistryEntry;
      if (isProcessAlive(parsed.pid)) {
        entries.push(parsed);
      }
    } catch {
      // Skip a malformed/mid-write entry rather than fail the whole listing.
    }
  }
  return entries;
}

/** Exported (Phase 4B) so coachClient.ts's discovery-file staleness check
 * (Step 3/4: "do NOT trust a stale discovery file blindly") reuses this
 * exact liveness check rather than a second implementation — same
 * single-source-of-truth discipline as the Python side's own
 * service/lifecycle.py: pid_is_alive(). */
export function isProcessAlive(pid: number): boolean {
  try {
    // Signal 0 checks existence without actually sending a signal — the
    // conventional cross-platform (including Windows Node.js) liveness
    // check documented for process.kill.
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
