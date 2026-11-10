/**
 * How a command's screen ends: one next action (a command to run or an
 * address to open) and, dimmed, the alternates. The Ink screen and the plain
 * reporter print the same lines.
 * @module lib/command-ending
 */

import type { CLIStore } from "../ui/store.js";

/** Store key a flow sets once it has finished. */
const ENDING_KEY = "ending";

export interface CommandEnding {
  /** What the next action is, e.g. "Next, run:" or "Open:". */
  lead: string;
  /** The command or address itself, shown bold in the accent colour. */
  target: string;
  /** Dim lines under it: other things to do, or a caveat worth knowing. */
  also?: readonly string[];
}

export function setEnding(store: CLIStore, ending: CommandEnding): void {
  store.updateData(ENDING_KEY, ending);
}

export function readEnding(store: CLIStore): CommandEnding | undefined {
  return store.currentState.data[ENDING_KEY];
}

/** The ending as plain text, for a run without a terminal. */
export function endingLines(ending: CommandEnding): string[] {
  return [
    "",
    `  ${ending.lead}  ${ending.target}`,
    ...(ending.also ?? []).map((line) => `  ${line}`),
  ];
}
