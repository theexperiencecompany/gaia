import type { FailureReason } from "../api/generated";
import type { DisplayState } from "./types";

/** The strip under a failed reply that already showed text or cards. */
export const REPLY_CUT_SHORT = "Response was cut short";

/** A failed reply's message when it showed nothing, by why it failed. */
export const REPLY_FAILURE_MESSAGE: Record<FailureReason, string> = {
  model_error: "An error occurred while processing your message",
  step_limit: "GAIA took too many steps on this and stopped before answering.",
  server_restart: "GAIA restarted while answering. It will answer again.",
};

/** The quiet line under a reply or task the user stopped. */
export const STOPPED_NOTE = "Stopped";

/** The loading row's words for what the server says GAIA is doing; thinking gets a playful line instead. */
export const DISPLAY_STATUS_TEXT: Record<
  Exclude<DisplayState, "thinking">,
  string
> = {
  idle: "",
  working: "Working on it",
  awaiting_approval: "Waiting for your approval",
};
