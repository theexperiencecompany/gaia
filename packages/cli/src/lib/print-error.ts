/**
 * A failure on stderr, worded as the Ink error box words it.
 * @module lib/print-error
 */

import { MARK } from "../ui/constants.js";

/** A failed step's cause and fix, each line under the label of the step's "✗" row. */
export function printStepError(message: string): void {
  const lines = message.split("\n").map((line) => `    ${line}`);
  process.stderr.write(`${lines.join("\n")}\n`);
}

/** "✗ <cause>" in the screen's column, then each further line (the next step, the log) under it. */
export function printError(message: string): void {
  const [cause = "", ...rest] = message.split("\n");
  const lines = [
    `  ${MARK.fail} ${cause}`,
    ...rest.map((line) => `    ${line}`),
  ];
  process.stderr.write(`${lines.join("\n")}\n`);
}
