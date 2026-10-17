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
    runFlow: (store) => runStartFlow(store, options),
    cancelHint:
      "GAIA may be partly started. Run 'gaia start' again to finish, or 'gaia stop'.",
  });
}
