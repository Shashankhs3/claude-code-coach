import * as assert from "assert";
import * as vscode from "vscode";

const EXTENSION_ID = "ShashankHS.claude-code-coach";

suite("Extension activation", () => {
  test("extension is present and activates", async () => {
    const ext = vscode.extensions.getExtension(EXTENSION_ID);
    assert.ok(ext, "extension should be discoverable by publisher.name");
    await ext!.activate();
    assert.strictEqual(ext!.isActive, true);
  });

  test("command claudeCodeCoach.openCoach is registered", async () => {
    const ext = vscode.extensions.getExtension(EXTENSION_ID);
    await ext!.activate();
    const commands = await vscode.commands.getCommands(true);
    assert.ok(
      commands.includes("claudeCodeCoach.openCoach"),
      "openCoach command must be registered on activation",
    );
  });

  test("Phase 3 commands (Inspect Prompt, Open Desktop Coach) are registered", async () => {
    const ext = vscode.extensions.getExtension(EXTENSION_ID);
    await ext!.activate();
    const commands = await vscode.commands.getCommands(true);
    assert.ok(commands.includes("claudeCodeCoach.inspectPrompt"));
    assert.ok(commands.includes("claudeCodeCoach.openDesktopCoach"));
  });

  test("Phase 3B commands (Pause Coaching, Resume Coaching) are registered", async () => {
    const ext = vscode.extensions.getExtension(EXTENSION_ID);
    await ext!.activate();
    const commands = await vscode.commands.getCommands(true);
    assert.ok(commands.includes("claudeCodeCoach.pauseCoaching"));
    assert.ok(commands.includes("claudeCodeCoach.resumeCoaching"));
  });

  test("internal panel-only commands are registered but not Command-Palette-visible", async () => {
    const ext = vscode.extensions.getExtension(EXTENSION_ID);
    await ext!.activate();
    const commands = await vscode.commands.getCommands(true);
    // Registered (the webview's command: URIs must resolve)...
    assert.ok(commands.includes("claudeCodeCoach.copySuggestedPrompt"));
    assert.ok(commands.includes("claudeCodeCoach.openSkillOrAgentPath"));
    // ...but not contributed to package.json's command palette list — these
    // exist only to be invoked from inside the panel's own HTML.
    const contributed: Array<{ command: string }> = ext!.packageJSON.contributes.commands;
    const contributedIds = contributed.map((c) => c.command);
    assert.ok(!contributedIds.includes("claudeCodeCoach.copySuggestedPrompt"));
    assert.ok(!contributedIds.includes("claudeCodeCoach.openSkillOrAgentPath"));
  });

  test("exactly the five user-facing commands are contributed (Phase 3B scope)", async () => {
    const ext = vscode.extensions.getExtension(EXTENSION_ID)!;
    const contributed: Array<{ command: string }> = ext.packageJSON.contributes.commands;
    const ids = contributed.map((c) => c.command).sort();
    assert.deepStrictEqual(ids, [
      "claudeCodeCoach.inspectPrompt",
      "claudeCodeCoach.openCoach",
      "claudeCodeCoach.openDesktopCoach",
      "claudeCodeCoach.pauseCoaching",
      "claudeCodeCoach.resumeCoaching",
    ]);
  });
});
