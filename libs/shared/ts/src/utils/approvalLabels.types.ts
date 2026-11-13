import type { ActionResult, ApprovalOutcome } from "../api/generated";
import type { ApprovalRequestData } from "../chat/approvals.types";

/** The three facts a card's label is read from; nothing stores the label itself. */
export type ApprovalEnd = Pick<
  ApprovalRequestData,
  "outcome" | "decider" | "action"
>;

/** One client's words for every card state, keyed by the facts that pick it. */
export interface ApprovalLabels<T> {
  pending: T;
  /** Approved by auto mode, before the action has a result. */
  autoApproved: T;
  outcome: Record<ApprovalOutcome, T>;
  /** An approved action's result wins over the approval that allowed it. */
  action: Record<ActionResult, T>;
}
