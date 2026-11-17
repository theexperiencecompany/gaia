import type { BatchDecisionOutcome } from "@shared/chat";

/** Why a batch item did not commit — the server's DecisionRefusal (hil_schemas.py). */
export const BATCH_OUTCOME_REASON = {
  ALREADY_DECIDED: "already_decided",
  NOT_FOUND: "not_found",
  ERROR: "error",
} as const;

/** Whether the server took this decision, found one already made, or no longer has the approval: a client lets go of it. */
export const isSettledOutcome = (outcome: BatchDecisionOutcome): boolean =>
  outcome.resolved ||
  outcome.reason === BATCH_OUTCOME_REASON.ALREADY_DECIDED ||
  outcome.reason === BATCH_OUTCOME_REASON.NOT_FOUND;
