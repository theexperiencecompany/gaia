import type { ApprovalDecisionResponse } from "../api/generated";
import type {
  ApprovalDecision,
  ApprovalRequestData,
  ApprovalStatus,
} from "../chat/approvals";
import { APPROVAL_REQUEST_TOOL_NAME } from "../chat/approvals";

/**
 * Settling an approval card, the one way both clients do it.
 *
 * A card settles from one of two signals: the `hil_approval_decided`
 * WebSocket frame (decided elsewhere, or revoked by the agent), or the
 * response to the user's own decision. Either can be the only one that
 * arrives, so each must be able to settle the card on its own.
 */

const KNOWN_STATUSES: ReadonlySet<string> = new Set<ApprovalStatus>([
  "pending",
  "approved",
  "denied",
  "timeout",
  "abandoned",
  "auto_approved",
  "revoked",
  "executed",
  "failed",
  "unknown",
]);

/** Statuses the backend publishes over `hil_approval_decided`. */
export const TERMINAL_APPROVAL_STATUSES: readonly ApprovalStatus[] = [
  "approved",
  "denied",
  "revoked",
  "executed",
  "failed",
  "unknown",
];

export function isKnownApprovalStatus(
  status: string,
): status is ApprovalStatus {
  return KNOWN_STATUSES.has(status);
}

/** One settled approval: which card, and the verdict it now shows. */
export interface ApprovalSettlement {
  conversation_id: string;
  approval_id: string;
  status: ApprovalStatus;
  feedback: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * Parse a `hil_approval_decided` frame. The backend publishes
 * `{type, data: {conversation_id, approval_id, status, feedback, version}}`
 * (ledger_decide._broadcast_decision). Returns null for anything else, and
 * for non-terminal statuses — the ledger row stays the truth.
 */
export function parseApprovalDecidedEvent(
  raw: unknown,
): ApprovalSettlement | null {
  if (!isRecord(raw) || !isRecord(raw.data)) return null;
  const { conversation_id, approval_id, status, feedback } = raw.data;
  if (typeof conversation_id !== "string" || conversation_id === "")
    return null;
  if (typeof approval_id !== "string" || approval_id === "") return null;
  if (typeof status !== "string") return null;
  if (!(TERMINAL_APPROVAL_STATUSES as readonly string[]).includes(status))
    return null;
  return {
    conversation_id,
    approval_id,
    status: status as ApprovalStatus,
    feedback: typeof feedback === "string" && feedback !== "" ? feedback : null,
  };
}

/**
 * The status a card shows after the user's own decision, or null when the
 * tap committed nothing and the card should re-enable for a retry.
 *
 * A refused commit that names a settled verdict means the row already moved
 * (another device, a delayed tap) — the card settles to that verdict. A
 * refusal naming nothing, or `pending`/`unknown`, is a stale-version conflict.
 */
export function statusAfterDecision(
  decision: ApprovalDecision,
  outcome: ApprovalDecisionResponse,
): ApprovalStatus | null {
  if (outcome.success) return decision === "approve" ? "approved" : "denied";
  const status = outcome.status ?? null;
  if (
    status === null ||
    status === "pending" ||
    status === "unknown" ||
    !isKnownApprovalStatus(status)
  ) {
    return null;
  }
  return status;
}

interface ToolDataLike {
  tool_name: string;
  data?: unknown;
}

/**
 * Flip the approval entry matching `approval_id` to its settled status.
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
        status: settlement.status,
        feedback: settlement.feedback ?? data.feedback ?? null,
      },
    };
  });
  return { entries: changed ? next : entries, changed };
}
