/**
 * Handler for `gaia uninstall` — remove a self-host install from this computer.
 * @module commands/uninstall/handler
 */

import { runCommandUI } from "../../lib/command-runner.js";
import { MARK } from "../../ui/constants.js";
import type { CLIStore } from "../../ui/store.js";
import {
  runUninstallFlow,
  UNINSTALL_OUTCOME_KEY,
  type UninstallOptions,
  type UninstallOutcome,
} from "./flow.js";
import { buildUninstallRows, UNINSTALL_HEADLINE } from "./summary.js";

const ROW_LABEL_WIDTH = 16;

function out(line = ""): void {
  process.stdout.write(`${line}\n`);
}

/** The same card the Ink screen shows, as plain text for a non-TTY run. */
function printUninstallSummary(store: CLIStore): void {
  const outcome = store.currentState.data[UNINSTALL_OUTCOME_KEY] as
    | UninstallOutcome
    | undefined;
  if (!outcome) return;
  out();
  out(`${MARK.ok} ${UNINSTALL_HEADLINE}`);
  for (const row of buildUninstallRows(outcome)) {
    out(`  ${row.label.padEnd(ROW_LABEL_WIDTH)}${row.text}`);
  }
}

export async function runUninstall(
  options: UninstallOptions = {},
): Promise<void> {
  await runCommandUI({
    command: "uninstall",
    whenNonInteractive: "plain",
    runFlow: (store) => runUninstallFlow(store, options),
    cancelHint:
      "GAIA may be partly removed. Run 'gaia uninstall' again to finish.",
    onPlainComplete: printUninstallSummary,
  });
}
