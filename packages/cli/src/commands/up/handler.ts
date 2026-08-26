/**
 * Handler for the `gaia up` command — one-command self-hosted setup.
 * @module commands/up/handler
 */

import { runCommandUI } from "../../lib/command-runner.js";
import type { CLIStore } from "../../ui/store.js";
import { runUpFlow } from "./flow.js";

function printPlainSummary(store: CLIStore): void {
  const data = store.currentState.data;
  if (data.error || !data.finished) return;
  const webPort = (data.upWebPort as number) ?? 3000;
  const apiPort = (data.upApiPort as number) ?? 8000;
  if (data.upNoStart !== true && data.upStillStarting === true) {
    console.info("\nGAIA is still starting...");
    console.info("  Containers are up but not answering yet.");
    console.info("  Run 'gaia status' to check progress.");
  } else {
    console.info("\nGAIA is ready!");
  }
  if (data.upNoStart !== true) {
    console.info(`  Web: http://localhost:${webPort}`);
    console.info(`  API: http://localhost:${apiPort}`);
  }
  console.info(
    `Finish setup in your browser: http://localhost:${webPort}/setup`,
  );
  if (data.webDriftDetected === true) {
    console.info(
      "Note: Web source changed since last build — run 'gaia up --build' to rebuild",
    );
  }
  console.info(
    "Next: gaia doctor — run 'gaia doctor' anytime to verify your installation",
  );
}

export async function runUp(
  options: {
    yes?: boolean;
    llmKey?: string;
    llmProvider?: "openrouter" | "gemini" | "custom";
    apiPort?: number;
    webPort?: number;
    pull?: boolean;
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
