import { ChildProcess, spawn } from "child_process";
import * as fs from "fs";
import * as path from "path";
import { appDir, getLastDiscoveryIssue, readDiscovery } from "./coachClient";

/**
 * Locates and, when nothing usable is already running, starts the bundled
 * Coach service — so an ordinary Marketplace install never requires the
 * user to have Python, and never requires them to run
 * `python -m claude_code_coach.service` themselves.
 *
 * The one rule every function here is built around: **never connect based
 * only on an open port, or on a process having started.** The only thing
 * that ever counts as "ready" is `readDiscovery()` from coachClient.ts
 * returning a validated record — correct shape, a live PID, a compatible
 * api_version — the exact same three checks every other caller in this
 * extension (and the Python side's own `read_discovery_file()`) already
 * uses. This module adds no second notion of "the service is up."
 *
 * De-duplication across multiple VS Code windows racing at activation is
 * best-effort only (a short-TTL lock file, `claimStartingLock` below) — the
 * actual correctness backstop is `service/lifecycle.py`'s own OS-level port
 * bind, which lets exactly one process win regardless of how many windows
 * spawn one at the same instant; a loser's `start_service()` call returns
 * `False` and that process exits(1) on its own (see
 * `service/__main__.py`) rather than corrupting anything.
 *
 * Service lifetime (Part 5): a spawned process is `detached` and `unref`'d
 * deliberately — it must outlive *this* VS Code window, since another
 * window, or the desktop app, may still be using it. Nothing in this
 * extension ever kills a service it did not itself just fail to reuse; the
 * bundled service, once started, keeps running as a background process
 * until the user stops it or the machine restarts — identical in spirit to
 * how the desktop app already treats its own embedded copy (only ever
 * stopping what it itself started, see `app.py`'s `aboutToQuit`).
 */

const READY_POLL_INTERVAL_MS = 250;
const READY_TIMEOUT_MS = 8000;
// Longer than READY_TIMEOUT_MS so a lock claimed just before a real spawn
// attempt is still held for that attempt's entire wait — see
// `claimStartingLock`'s docstring for why this doesn't need to be exact.
const STARTING_LOCK_TTL_MS = 10000;
const SPAWN_RETRY_COOLDOWN_MS = 30000;
const MAX_CONSECUTIVE_FAILURES_BEFORE_BACKOFF = 3;

// Module-level, per-window-process state — deliberately not persisted
// anywhere. A window that's been failing to start the service backs off
// spawn attempts after a few tries rather than hammering `spawn()` every
// refresh tick forever; a fresh window (or this one after being reloaded)
// starts with a clean slate rather than inheriting another window's streak.
let lastSpawnAttemptAt = 0;
let consecutiveFailures = 0;

export function resetBackoffStateForTests(): void {
  lastSpawnAttemptAt = 0;
  consecutiveFailures = 0;
}

/** Pre-release scope (Part 3): Windows x64 only. Any other platform/arch
 * returns undefined — `resolveBundledServicePath` and therefore
 * `ensureServiceRunning` then become a safe, silent no-op there, never a
 * guess at a path that can't exist. */
function platformDir(): string | undefined {
  if (process.platform === "win32" && process.arch === "x64") {
    return "win32-x64";
  }
  return undefined;
}

/** The bundled exe's path, or undefined if there isn't one for this
 * platform/build — dev mode running compiled-but-unbundled `out/`, an
 * unsupported OS, or a package that was built without running
 * `packaging/build_vscode_service.ps1` first. Never hard-codes a system
 * Python path, never assumes Python is installed at all — this is a
 * self-contained executable this extension ships itself. */
export function resolveBundledServicePath(extensionPath: string): string | undefined {
  const dir = platformDir();
  if (!dir) {
    return undefined;
  }
  const exePath = path.join(extensionPath, "bundled", dir, "CoachService", "CoachService.exe");
  try {
    if (fs.statSync(exePath).isFile()) {
      return exePath;
    }
  } catch {
    // Not present. Never invented, never assumed — the caller treats this
    // exactly like "no bundled service available."
  }
  return undefined;
}

function startingLockPath(): string {
  return path.join(appDir(), "service_starting.lock");
}

/** Best-effort cross-window de-dup only — see the module docstring for the
 * real correctness guarantee. A lock older than its TTL is treated as
 * abandoned (a window that claimed it was reloaded, crashed, or simply
 * finished) and reclaimed, so a stale lock can never permanently block
 * every future activation from trying again. Exported so duplicate-start
 * prevention can be tested directly rather than by orchestrating two real
 * concurrent process spawns. */
export function claimStartingLock(ttlMs: number = STARTING_LOCK_TTL_MS): boolean {
  const lockPath = startingLockPath();
  try {
    const stat = fs.statSync(lockPath);
    if (Date.now() - stat.mtimeMs < ttlMs) {
      return false;
    }
  } catch {
    // No lock file yet — fall through and claim it.
  }
  try {
    fs.mkdirSync(appDir(), { recursive: true });
    fs.writeFileSync(lockPath, String(process.pid), { encoding: "utf-8" });
    return true;
  } catch {
    // Can't even write the lock file — don't let that block starting the
    // service either; just proceed without the (best-effort-only) de-dup.
    return true;
  }
}

export function releaseStartingLock(): void {
  try {
    fs.rmSync(startingLockPath(), { force: true });
  } catch {
    // Best effort — a leftover lock is harmless; it just expires via TTL.
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Polls the *real* discovery check (`readDiscovery()`, shape + PID
 * liveness + api_version) — never a bare "is the port open" probe. */
export async function waitForReady(
  timeoutMs: number = READY_TIMEOUT_MS,
  pollIntervalMs: number = READY_POLL_INTERVAL_MS,
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  do {
    if (readDiscovery()) {
      return true;
    }
    await sleep(pollIntervalMs);
  } while (Date.now() < deadline);
  return false;
}

/** Spawns `command args` detached (see the module docstring's "Service
 * lifetime" note — this process must be able to outlive the caller) and
 * waits for `readDiscovery()` to validate it, up to `timeoutMs`. Extracted
 * from `ensureServiceRunning` specifically so tests can exercise real
 * spawn-and-wait behavior (a slow-to-start process, one that never starts,
 * one that crashes right after starting) against any real spawnable
 * command — not only the actual bundled CoachService.exe, which a unit
 * test should not need to have been built first. */
export async function spawnAndWaitForReady(
  command: string,
  args: string[] = [],
  timeoutMs: number = READY_TIMEOUT_MS,
): Promise<{ ready: boolean; child?: ChildProcess; spawnError?: Error }> {
  let spawnError: Error | undefined;
  let child: ChildProcess | undefined;
  try {
    child = spawn(command, args, {
      // Must outlive this VS Code window (Part 5: another window, or the
      // desktop app, may still need it) — detached + unref, never a child
      // this process's own exit could take down with it.
      detached: true,
      // docs/STANDALONE_SERVICE.md's own documented gotcha: an unread pipe
      // can fill its OS buffer under load and block the service's request
      // handling entirely. Never redirect these into a pipe this process
      // doesn't drain.
      stdio: "ignore",
      windowsHide: true,
    });
    child.unref();
    child.on("error", (err) => {
      // Failed to even launch (e.g. a missing dependency DLL, or the file
      // doesn't exist) — recorded so a test/caller can see *why*, though
      // waitForReady's own timeout is what actually surfaces this in
      // production (ensureServiceRunning only reports a generic reason).
      spawnError = err;
    });
  } catch (err) {
    spawnError = err instanceof Error ? err : new Error(String(err));
  }

  const ready = await waitForReady(timeoutMs);
  return { ready, child, spawnError };
}

export interface EnsureServiceResult {
  /** A usable service was already reachable — nothing was started. */
  alreadyRunning: boolean;
  /** This call spawned the bundled service and it became ready. */
  started: boolean;
  /** Present when neither of the above happened — human-readable, shown
   * only in logs/tooltips, never as a fabricated success. */
  reason?: string;
}

/**
 * The one entry point `extension.ts` calls. Idempotent and safe to call on
 * every poll tick: an already-reachable service returns immediately with
 * `alreadyRunning: true` and starts nothing. A stale discovery file (dead
 * PID) is never "already running" — `readDiscovery()` already treats that
 * as absent, so this function proceeds straight to a start attempt exactly
 * as if nothing had ever run.
 */
export async function ensureServiceRunning(extensionPath: string): Promise<EnsureServiceResult> {
  if (readDiscovery()) {
    return { alreadyRunning: true, started: false };
  }

  const now = Date.now();
  if (
    consecutiveFailures >= MAX_CONSECUTIVE_FAILURES_BEFORE_BACKOFF &&
    now - lastSpawnAttemptAt < SPAWN_RETRY_COOLDOWN_MS
  ) {
    return { alreadyRunning: false, started: false, reason: "backing off after repeated failed starts" };
  }

  const exePath = resolveBundledServicePath(extensionPath);
  if (!exePath) {
    return { alreadyRunning: false, started: false, reason: "no bundled Coach service for this platform" };
  }

  if (!claimStartingLock()) {
    // Another window (or a previous tick in this one) is already trying —
    // this call's job was "make sure something is starting," not
    // "be the one that starts it." Wait on the same real readiness check
    // rather than racing a second spawn.
    const ready = await waitForReady(READY_TIMEOUT_MS);
    return ready
      ? { alreadyRunning: false, started: false }
      : { alreadyRunning: false, started: false, reason: "waiting on another window's in-progress start" };
  }

  lastSpawnAttemptAt = now;
  try {
    // `--port 0` binds an ephemeral port (the same flag value the
    // Python-side test suite already uses for exactly this reason — see
    // docs/STANDALONE_SERVICE.md) rather than the fixed default port —
    // this spawn attempt can then never fail merely because something
    // else happens to be transiently bound to that fixed port at this
    // exact instant. Every reader still discovers the real bound port from
    // service.json, never assumes which one — so this changes nothing
    // about how any client connects.
    const { ready } = await spawnAndWaitForReady(exePath, ["--port", "0"], READY_TIMEOUT_MS);
    if (ready) {
      consecutiveFailures = 0;
      return { alreadyRunning: false, started: true };
    }
    consecutiveFailures += 1;
    return {
      alreadyRunning: false,
      started: false,
      reason: getLastDiscoveryIssue() ?? "bundled Coach service did not become ready in time",
    };
  } finally {
    releaseStartingLock();
  }
}
