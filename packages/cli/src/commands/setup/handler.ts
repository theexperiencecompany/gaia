/**
 * Handler for the 'setup' command — interactive env configuration wizard.
 * @module commands/setup/handler
 */

import { runCommandUI } from "../../lib/command-runner.js";
import { runSetupFlow } from "./flow.js";

export async function runSetup(): Promise<void> {
  await runCommandUI({
    command: "setup",
    whenNonInteractive: "fail",
    runFlow: runSetupFlow,
  });
}
