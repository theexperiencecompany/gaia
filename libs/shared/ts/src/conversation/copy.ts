import type { DisplayState } from "./types";

/** The label under a send that never reached the server, next to its retry. */
export const SEND_NOT_DELIVERED = "Not delivered";

/** The quiet line under a reply or task the user stopped. */
export const STOPPED_NOTE = "Stopped";

/** The line under a tool's output or a subagent's result the server cut, naming the whole text's length; an old card keeps none of it. */
export function outputTruncatedNote(
  originalLength: number,
  keptAny: boolean,
): string {
  const length = originalLength.toLocaleString("en-US");
  return keptAny
    ? `Showing the first part only. The full text is ${length} characters long.`
    : `This text is no longer stored. It was ${length} characters long.`;
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
