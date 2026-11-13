import type { ApprovalRequestData, ApprovalStatus } from "@gaia/shared/chat";
import { approvalOutcomeLabel } from "@gaia/shared/chat";
import type { ApprovalSettlement } from "@gaia/shared/utils";
import { settleApprovalToolData } from "@gaia/shared/utils";
import type { Message } from "@/features/chat/api/chat-api";

export interface ApprovalMeta {
  label: string;
  color: string;
}

/**
 * Resolved-card meta for every non-pending status. The card derefs this map
 * for any `data.status !== "pending"`, so all nine ledger states must be
 * present — a missing key crashes the card on ledger-terminal statuses
 * (revoked/executed/failed/unknown).
 */
export const APPROVAL_RESOLVED_META: Record<
  Exclude<ApprovalStatus, "pending">,
  ApprovalMeta
> = {
  auto_approved: { label: "Ran automatically", color: "#34d399" },
  approved: { label: "Approved", color: "#34d399" },
  denied: { label: "Declined", color: "#f87171" },
  timeout: { label: "Timed out", color: "#fbbf24" },
  abandoned: { label: "Dropped", color: "#a1a1aa" },
  executed: { label: "Executed", color: "#34d399" },
  failed: { label: "Failed", color: "#f87171" },
  unknown: { label: "Unknown", color: "#fbbf24" },
  revoked: { label: "Withdrawn", color: "#a1a1aa" },
};

/**
 * Activity-row chips for every settled state. Labels match web's
 * SubagentRow APPROVAL_CHIP (Executed/success, Failed/danger,
 * Unknown/warning); revoked renders as a tombstone-style chip since the
 * mobile timeline has no separate tombstone surface.
 */
export const APPROVAL_CHIP_META: Record<
  Exclude<ApprovalStatus, "pending">,
  ApprovalMeta
> = {
  approved: { label: "Approved", color: "#22c55e" },
  auto_approved: { label: "Auto-approved", color: "#22c55e" },
  denied: { label: "Denied", color: "#ef4444" },
  timeout: { label: "Expired", color: "#71717a" },
  abandoned: { label: "Expired", color: "#71717a" },
  executed: { label: "Executed", color: "#22c55e" },
  failed: { label: "Failed", color: "#ef4444" },
  unknown: { label: "Unknown", color: "#eab308" },
  revoked: { label: "Withdrawn", color: "#71717a" },
};

/**
 * One-line outcome for a settled card. Shared `approvalOutcomeLabel` returns
 * "" for executed/failed/unknown, so fall
 * back to per-status copy here — preferring explicit feedback when present.
 */
export function approvalOutcomeText(data: ApprovalRequestData): string {
  const base = approvalOutcomeLabel(data);
  if (base.trim() !== "") return base;
  const feedback = data.feedback?.trim();
  if (feedback) return feedback;
  switch (data.status) {
    case "executed":
      return "The approved action ran";
    case "failed":
      return "The approved action failed";
    case "unknown":
      return "Outcome unknown";
    default:
      return "";
  }
}

/**
 * Flip the stored card matching `approval_id` to its terminal status.
 * Pure — operates on a Message snapshot, never mutates the input. Returns
 * the original array by identity when nothing matched so callers can skip
 * store writes and persistence.
 */
export function applyApprovalDecisionToMessages(
  messages: Message[],
  event: ApprovalSettlement,
): { messages: Message[]; changed: boolean } {
  let changed = false;
  const next = messages.map((message) => {
    const { entries, changed: entryChanged } = settleApprovalToolData(
      message.toolData,
      event,
    );
    if (!entryChanged) return message;
    changed = true;
    return { ...message, toolData: entries };
  });
  return { messages: changed ? next : messages, changed };
}
