import * as path from "path";
import { runTests } from "@vscode/test-electron";

async function main() {
  try {
    const extensionDevelopmentPath = path.resolve(__dirname, "../../");
    const extensionTestsPath = path.resolve(__dirname, "./suite/index");
    // Launch with an isolated, throwaway user-data-dir/extensions-dir so a
    // real VS Code install on this machine is never touched by the test run.
    await runTests({
      extensionDevelopmentPath,
      extensionTestsPath,
      launchArgs: ["--disable-workspace-trust"],
    });
  } catch (err) {
    console.error("Failed to run extension tests", err);
    process.exit(1);
  }
}

void main();
