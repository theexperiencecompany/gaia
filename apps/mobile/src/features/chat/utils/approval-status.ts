import type { ApprovalLabels, ApprovalRequestData } from "@gaia/shared/chat";
import { approvalOutcomeLabel } from "@gaia/shared/chat";
import type { ApprovalSettlement } from "@gaia/shared/utils";
import { settleApprovalToolData } from "@gaia/shared/utils";
import type { Message } from "@/features/chat/api/chat-api";

export interface ApprovalMeta {
  label: string;
  color: string;
}

/** Resolved-card meta for every way an approval ends; pending has none. */
export const APPROVAL_RESOLVED_META: ApprovalLabels<ApprovalMeta | null> = {
  pending: null,
  autoApproved: { label: "Ran automatically", color: "#34d399" },
  outcome: {
    approved: { label: "Approved", color: "#34d399" },
    denied: { label: "Declined", color: "#f87171" },
    expired: { label: "Timed out", color: "#fbbf24" },
    cancelled: { label: "Cancelled", color: "#a1a1aa" },
    withdrawn: { label: "Withdrawn", color: "#a1a1aa" },
  },
  action: {
    executing: { label: "Approved", color: "#34d399" },
    executed: { label: "Executed", color: "#34d399" },
    failed: { label: "Failed", color: "#f87171" },
    unknown: { label: "Unknown", color: "#fbbf24" },
  },
};

/**
 * Activity-row chips for every settled state. Labels match web's
 * ToolCallRow APPROVAL_CHIP; a withdrawn card renders as a tombstone-style
 * chip since the mobile timeline has no separate tombstone surface.
 */
export const APPROVAL_CHIP_META: ApprovalLabels<ApprovalMeta | null> = {
  pending: null,
  autoApproved: { label: "Auto-approved", color: "#22c55e" },
  outcome: {
    approved: { label: "Approved", color: "#22c55e" },
    denied: { label: "Denied", color: "#ef4444" },
    expired: { label: "Expired", color: "#71717a" },
    cancelled: { label: "Cancelled", color: "#71717a" },
    withdrawn: { label: "Withdrawn", color: "#71717a" },
  },
  action: {
    executing: { label: "Approved", color: "#22c55e" },
    executed: { label: "Executed", color: "#22c55e" },
    failed: { label: "Failed", color: "#ef4444" },
    unknown: { label: "Unknown", color: "#eab308" },
  },
};

/** One-line outcome for a settled card: the shared line, else the feedback. */
export function approvalOutcomeText(data: ApprovalRequestData): string {
  const base = approvalOutcomeLabel(data);
  if (base.trim() !== "") return base;
  return data.feedback?.trim() ?? "";
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
