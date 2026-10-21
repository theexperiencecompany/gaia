/**
 * A failure on stderr, worded as the Ink error box words it.
 * @module lib/print-error
 */

import { MARK } from "../ui/constants.js";

/** "✗ <cause>" in the screen's column, then each further line (the next step, the log) under it. */
export function printError(message: string): void {
  const [cause = "", ...rest] = message.split("\n");
  const lines = [
    `  ${MARK.fail} ${cause}`,
    ...rest.map((line) => `    ${line}`),
  ];
  process.stderr.write(`${lines.join("\n")}\n`);
}
