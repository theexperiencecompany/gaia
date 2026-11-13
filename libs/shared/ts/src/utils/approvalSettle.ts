import type {
  ActionResult,
  ApprovalDecider,
  ApprovalDecisionResponse,
  ApprovalOutcome,
} from "../api/generated";
import type {
  ApprovalDecision,
  ApprovalEnd,
  ApprovalRequestData,
} from "../chat/approvals";
import { APPROVAL_REQUEST_TOOL_NAME } from "../chat/approvals";

/**
 * Settling an approval card, the one way both clients do it.
 *
 * A card settles from one of two signals: the `hil_approval_decided`
 * WebSocket frame (decided elsewhere, or withdrawn by the agent), or the
 * response to the user's own decision. Either can be the only one that
 * arrives, so each must be able to settle the card on its own.
 */

// Keyed by the generated unions, so a value the API adds or drops fails the build here.
const OUTCOMES: Record<ApprovalOutcome, true> = {
  approved: true,
  denied: true,
  expired: true,
  cancelled: true,
  withdrawn: true,
};
const DECIDERS: Record<ApprovalDecider, true> = { user: true, auto: true };
const ACTIONS: Record<ActionResult, true> = {
  executing: true,
  executed: true,
  failed: true,
  unknown: true,
};

const isOutcome = (value: unknown): value is ApprovalOutcome =>
  typeof value === "string" && Object.hasOwn(OUTCOMES, value);
const isDecider = (value: unknown): value is ApprovalDecider =>
  typeof value === "string" && Object.hasOwn(DECIDERS, value);
const isAction = (value: unknown): value is ActionResult =>
  typeof value === "string" && Object.hasOwn(ACTIONS, value);

/** One settled approval: which card, and how it ended. */
export interface ApprovalSettlement extends ApprovalEnd {
  conversation_id: string;
  approval_id: string;
  outcome: ApprovalOutcome;
  feedback: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * Parse a `hil_approval_decided` frame. The backend publishes
 * `{type, data: {conversation_id, approval_id, outcome, decider, action, feedback, version}}`
 * (ledger_decide._broadcast_decision). Returns null for anything else.
 */
export function parseApprovalDecidedEvent(
  raw: unknown,
): ApprovalSettlement | null {
  if (!isRecord(raw) || !isRecord(raw.data)) return null;
  const { conversation_id, approval_id, outcome, decider, action, feedback } =
    raw.data;
  if (typeof conversation_id !== "string" || conversation_id === "")
    return null;
  if (typeof approval_id !== "string" || approval_id === "") return null;
  if (!isOutcome(outcome)) return null;
  return {
    conversation_id,
    approval_id,
    outcome,
    decider: isDecider(decider) ? decider : null,
    action: isAction(action) ? action : null,
    feedback: typeof feedback === "string" && feedback !== "" ? feedback : null,
  };
}

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

interface ToolDataLike {
  tool_name: string;
  data?: unknown;
}

/**
 * Flip the approval entry matching `approval_id` to how it ended.
 * Pure; returns the input by identity when nothing matched, so callers can
 * skip store writes and persistence.
 */
export function settleApprovalToolData<T extends ToolDataLike>(
  entries: T[] | null | undefined,
  settlement: Omit<ApprovalSettlement, "conversation_id">,
): { entries: T[] | undefined; changed: boolean } {
  if (!entries) return { entries: undefined, changed: false };
  let changed = false;
  const next = entries.map((entry) => {
    if (entry.tool_name !== APPROVAL_REQUEST_TOOL_NAME) return entry;
    const data = entry.data as Partial<ApprovalRequestData> | null | undefined;
    if (!data || data.approval_id !== settlement.approval_id) return entry;
    changed = true;
    return {
      ...entry,
      data: {
        ...(data as ApprovalRequestData),
        outcome: settlement.outcome,
        decider: settlement.decider ?? null,
        action: settlement.action ?? null,
        feedback: settlement.feedback ?? data.feedback ?? null,
      },
    };
  });
  return { entries: changed ? next : entries, changed };
}
