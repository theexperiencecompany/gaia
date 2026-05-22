/**
 * Handler for the 'init' command — clones the GAIA repo.
 * @module commands/init/handler
 */

import { runCommandUI } from "../../lib/command-runner.js";
import { runInitFlow } from "./flow.js";

export async function runInit(
  options: { branch?: string } = {},
): Promise<void> {
  await runCommandUI({
    command: "init",
    whenNonInteractive: "fail",
    runFlow: (store) => runInitFlow(store, options.branch),
  });
}
