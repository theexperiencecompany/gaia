/**
 * Handler for the 'stop' command — stops running services.
 * @module commands/stop/handler
 */

import { runCommandUI } from "../../lib/command-runner.js";
import type { StopServicesOptions } from "../../lib/service-starter.js";
import { runStopFlow } from "./flow.js";

export async function runStop(options?: StopServicesOptions): Promise<void> {
  await runCommandUI({
    command: "run",
    whenNonInteractive: "plain",
    runFlow: (store) => runStopFlow(store, options),
    cancelHint: "GAIA may still be partly running. Run 'gaia stop' again.",
  });
}
