/**
 * Handler for the `gaia up` command — one-command self-hosted setup.
 * @module commands/up/handler
 */

import type { LlmProvider } from "../../lib/answers.js";
import { runCommandUI } from "../../lib/command-runner.js";
import type { CLIStore } from "../../ui/store.js";
import { runUpFlow } from "./flow.js";

function printPlainSummary(store: CLIStore): void {
  const data = store.currentState.data;
  if (data.error || !data.finished) return;
  const webUrl = data.upWebUrl as string;
  const apiUrl = data.upApiUrl as string;
  if (data.upNoStart !== true && data.upStillStarting === true) {
    console.info("\nGAIA is still starting...");
    console.info("  Containers are up but not answering yet.");
    console.info("  Run 'gaia status' to check progress.");
  } else {
    console.info("\nGAIA is ready!");
  }
  if (data.upNoStart !== true) {
    console.info(`  Web: ${webUrl}`);
    console.info(`  API: ${apiUrl}`);
  }
  console.info(`Finish setup in your browser: ${webUrl}/setup`);
  console.info(
    "Next: gaia doctor — run 'gaia doctor' anytime to verify your installation",
  );
}

export async function runUp(
  options: {
    yes?: boolean;
    llmKey?: string;
    llmProvider?: LlmProvider;
    domain?: string;
    webPort?: number;
    build?: boolean;
    noStart?: boolean;
    forceDevTree?: boolean;
  } = {},
): Promise<void> {
  await runCommandUI({
    command: "up",
    whenNonInteractive: "plain",
    autoResolve: [["exit", "exit"]],
    runFlow: (store) => runUpFlow(store, options),
    onPlainComplete: printPlainSummary,
  });
}
