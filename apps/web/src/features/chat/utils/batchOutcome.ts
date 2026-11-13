import type { ApprovalEnd, BatchDecisionOutcome } from "@shared/chat";

/** Why a batch item did not commit — the server's vocabulary (ledger_decide.py). */
export const BATCH_OUTCOME_REASON = {
  NOT_FOUND: "not_found",
  STALE: "stale",
  ERROR: "error",
} as const;

/**
 * Settle a batch item to the server's reported end, not the tapped button.
 *
 * A `not_found` batch outcome means the row was already decided elsewhere
 * (lost CAS race, other tab, withdrawn) — painting the just-tapped verdict
 * overwrites the real one (e.g. approve tap over an already-denied row).
 * Prefer the server's outcome; fall back to the tapped verdict only when the
 * server sent none (old path).
 */
export function resolveBatchOutcome(
  outcome: BatchDecisionOutcome,
  tapped: ApprovalEnd,
): ApprovalEnd {
  if (!outcome.outcome) return tapped;
  return {
    outcome: outcome.outcome,
    decider: null,
    action: outcome.action ?? null,
  };
}
