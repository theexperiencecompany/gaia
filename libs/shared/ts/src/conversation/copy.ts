import type { DisplayState } from "./types";

/** The label under a send that never reached the server, next to its retry. */
export const SEND_NOT_DELIVERED = "Not delivered";

/** The quiet line under a reply or task the user stopped. */
export const STOPPED_NOTE = "Stopped";

/** The line under a tool's output or a subagent's result the server cut, naming the whole text's length. */
export function outputTruncatedNote(originalLength: number): string {
  return `Showing the first part only. The full text is ${originalLength.toLocaleString("en-US")} characters long.`;
}

/** The loading row's words for what the server says GAIA is doing; thinking gets a playful line instead. */
export const DISPLAY_STATUS_TEXT: Record<
  Exclude<DisplayState, "thinking">,
  string
> = {
  idle: "",
  working: "Working on it",
  awaiting_approval: "Waiting for your approval",
};
