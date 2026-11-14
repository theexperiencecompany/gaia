import type { ApprovalDecisionResponse } from "../api/generated";
import type { ApprovalDecision, ApprovalEnd } from "../chat/approvals";

/** How a card the user decided ends, before the server says anything more. */
export function decidedEnd(decision: ApprovalDecision): ApprovalEnd {
  return {
    outcome: decision === "approve" ? "approved" : "denied",
    decider: "user",
    action: null,
  };
}

/**
 * How a card ends after the user's own decision, or null when the tap
 * committed nothing and the card should re-enable for a retry.
 *
 * A refused commit that names an outcome means the row already moved
 * (another device, a delayed tap): the card settles to it. A refusal naming
 * none is a stale-version conflict on a row that is still pending.
 */
export function endAfterDecision(
  decision: ApprovalDecision,
  response: ApprovalDecisionResponse,
): ApprovalEnd | null {
  const action = response.action ?? null;
  if (response.success) return { ...decidedEnd(decision), action };
  const outcome = response.outcome ?? null;
  return outcome === null ? null : { outcome, decider: null, action };
}
