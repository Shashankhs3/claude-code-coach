import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import { signalFilePath, appDir } from "./coachClient";

/**
 * Watches vscode_signal.txt — written by whichever Coach service process's
 * background drain loop (claude_code_coach/service/lifecycle.py; the
 * desktop app's embedded copy, or the Phase 4A standalone
 * `python -m claude_code_coach.service` process — the file format and
 * write path are identical either way) is currently running, every time a
 * new runtime hook event is persisted. This lets the extension react promptly
 * to real Claude Code activity without polling the full Coach state on a
 * tight interval. A fallback poll (see extension.ts) still exists in case
 * the watcher is missed (e.g. the file didn't exist yet when the watcher
 * was created), so this is an optimization, never a single point of
 * failure for freshness.
 */
export class FileSignalWatcher implements vscode.Disposable {
  private watcher: vscode.FileSystemWatcher | undefined;
  private readonly emitter = new vscode.EventEmitter<void>();
  readonly onDidChange = this.emitter.event;

  start(): void {
    // Watch the containing directory rather than the file path directly —
    // vscode.workspace.createFileSystemWatcher needs a glob pattern, and
    // the signal file may not exist yet on first activation (no hook
    // events fired this session).
    try {
      const dir = appDir();
      if (!fs.existsSync(dir)) {
        return;
      }
      const pattern = new vscode.RelativePattern(dir, path.basename(signalFilePath()));
      this.watcher = vscode.workspace.createFileSystemWatcher(pattern);
      this.watcher.onDidChange(() => this.emitter.fire());
      this.watcher.onDidCreate(() => this.emitter.fire());
    } catch {
      // Watching is a best-effort enhancement — the fallback poll covers us.
    }
  }

  dispose(): void {
    this.watcher?.dispose();
    this.emitter.dispose();
  }
}
