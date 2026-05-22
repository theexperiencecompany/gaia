/**
 * Handler for the 'start' command — starts services via Docker Compose.
 * @module commands/start/handler
 */

import { runCommandUI } from "../../lib/command-runner.js";
import type { StartServicesOptions } from "../../lib/service-starter.js";
import { runStartFlow } from "./flow.js";

export async function runStart(options?: StartServicesOptions): Promise<void> {
  await runCommandUI({
    command: "start",
    whenNonInteractive: "plain",
    autoResolve: [["exit"]],
    runFlow: (store) => runStartFlow(store, options),
  });
}
