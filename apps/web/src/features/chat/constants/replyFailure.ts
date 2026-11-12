import type { FailureReason } from "@shared/api/generated";

/** The strip under a failed reply that already showed text or cards. */
export const REPLY_CUT_SHORT = "Response was cut short";

/** A failed reply's message when it showed nothing, by why it failed. */
export const REPLY_FAILURE_MESSAGE: Record<FailureReason, string> = {
  model_error: "An error occurred while processing your message",
  step_limit: "GAIA took too many steps on this and stopped before answering.",
  server_restart: "GAIA restarted while answering. It will answer again.",
};
