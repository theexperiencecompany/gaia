/**
 * Handler for the `gaia up` command — one-command self-hosted setup.
 * @module commands/up/handler
 */

import { runCommandUI } from "../../lib/command-runner.js";
import type { LlmProvider } from "../../lib/llm-flags.js";
import type { CLIStore } from "../../ui/store.js";
import {
  codeSandboxSummary,
  DOCKER_GROUP_NOTE,
  runUpFlow,
  savedProviderSummary,
  upHeadline,
} from "./flow.js";

export function printUpSummary(store: CLIStore): void {
  const data = store.currentState.data;
  if (data.error || !data.finished) return;
  const webUrl = data.upWebUrl as string;
  const apiUrl = data.upApiUrl as string;
  const noStart = data.upNoStart === true;
  const stillStarting = !noStart && data.upStillStarting === true;
  console.info(`\n${upHeadline({ noStart, stillStarting })}`);
  if (noStart) {
    console.info("  Start it with 'gaia start'.");
  } else {
    if (stillStarting) {
      console.info("  Containers are up but not answering yet.");
      console.info("  Run 'gaia status' to check progress.");
    }
    console.info("  Open GAIA at:");
    for (const url of data.upReachableUrls as string[]) {
      console.info(`    ${url}`);
    }
    console.info(`  API: ${apiUrl}`);
  }
  if (data.upSetupComplete !== true) {
    console.info(`Finish setup in your browser: ${webUrl}/setup`);
  }
  if (data.upSavedProvider) {
    console.info(savedProviderSummary(data.upSavedProvider as string));
  }
  console.info(codeSandboxSummary(data.upCodeSandbox === true));
  if (data.upJoinedDockerGroup === true) console.info(DOCKER_GROUP_NOTE);
  console.info(
    "Next: gaia doctor — run 'gaia doctor' anytime to verify your installation",
  );
}

export async function runUp(
  options: {
    yes?: boolean;
    llmKey?: string;
    llmProvider?: LlmProvider;
    llmBaseUrl?: string;
    llmModel?: string;
    domain?: string;
    webPort?: number;
    build?: boolean;
    codeSandbox?: boolean;
    noStart?: boolean;
    forceDevTree?: boolean;
  } = {},
): Promise<void> {
  await runCommandUI({
    command: "up",
    whenNonInteractive: "plain",
    runFlow: (store) => runUpFlow(store, options),
    onPlainComplete: printUpSummary,
  });
}
