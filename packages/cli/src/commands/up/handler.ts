/**
 * Handler for the `gaia up` command — one-command self-hosted setup.
 * @module commands/up/handler
 */

import type { UpFlags } from "../../lib/answers.js";
import { runCommandUI } from "../../lib/command-runner.js";
import { MARK } from "../../ui/constants.js";
import type { CLIStore } from "../../ui/store.js";
import { runUpFlow } from "./flow.js";
import { buildUpSummary, NEXT_COMMANDS } from "./summary.js";

const ROW_LABEL_WIDTH = 16;
const COMMAND_WIDTH = 14;

/** One line of the card, two columns in like the screen's. */
function out(line = ""): void {
  process.stdout.write(line ? `  ${line}\n` : "\n");
}

/** The same card the Ink screen shows, as plain text for a non-TTY run. */
export function printUpSummary(store: CLIStore): void {
  const outcome = store.currentState.data.upOutcome;
  if (!outcome) return;
  const summary = buildUpSummary(outcome);
  out();
  out(`${summary.tone === "success" ? `${MARK.ok} ` : ""}${summary.headline}`);
  for (const row of summary.rows) {
    out(`  ${row.label.padEnd(ROW_LABEL_WIDTH)}${row.text}`);
  }
  out();
  for (const [command, purpose] of NEXT_COMMANDS) {
    out(`  ${command.padEnd(COMMAND_WIDTH)}${purpose}`);
  }
}

export async function runUp(options: UpFlags = {}): Promise<void> {
  await runCommandUI({
    command: "up",
    whenNonInteractive: "plain",
    runFlow: (store) => runUpFlow(store, options),
    cancelHint:
      "GAIA may be partly set up. Run 'gaia up' again to finish, or 'gaia stop'.",
    onPlainComplete: printUpSummary,
  });
}
