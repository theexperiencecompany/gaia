import type {
  ApprovalRequestData,
  ApprovalStatus,
  HilMode,
  HilPreferences,
} from "./approvals.types";
import type { StreamToolDataEntry } from "./streaming";

export type {
  ApprovalDecision,
  ApprovalDecisionPayload,
  ApprovalRequestData,
  ApprovalScope,
  ApprovalStatus,
  BatchApprovalDecisionPayload,
  BatchApprovalDecisionResponse,
  BatchDecisionItem,
  BatchDecisionOutcome,
  HilMode,
  HilPreferences,
} from "./approvals.types";

export const APPROVAL_REQUEST_TOOL_NAME = "approval_request";

export const DEFAULT_HIL_MODE: HilMode = "always_allow";

/** A decided approval — no longer actionable, kept as a receipt. */
export function isSettled(status: ApprovalStatus): boolean {
  return status !== "pending";
}

/** Whether a tool needs approval — i.e. is in the gated set the mode acts on. */
export function toolAsks(
  prefs: HilPreferences | undefined,
  name: string,
  destructive: boolean,
): boolean {
  return prefs?.tool_overrides?.[name] ?? destructive;
}

/**
 * Override to store for a user's choice: only diffs from the tool's default
 * classification are kept, so matching the default clears the override (null).
 */
export function toolOverrideValue(
  ask: boolean,
  destructive: boolean,
): boolean | null {
  return ask === destructive ? null : ask;
}

/** One line explaining how a settled approval was decided. */
export function approvalOutcomeLabel(data: ApprovalRequestData): string {
  switch (data.status) {
    case "auto_approved":
      return data.auto_reason?.trim() || "Matched what you asked for";
    case "approved":
      return "You approved this";
    case "denied":
      return data.feedback?.trim() || "You declined this";
    case "timeout":
      return "Expired without a response";
    case "abandoned":
      return "Dropped when you moved on";
    default:
      return "";
  }
}

const approvalId = (entry: StreamToolDataEntry): string | null => {
  if (entry.tool_name !== APPROVAL_REQUEST_TOOL_NAME) return null;
  const data = entry.data as Partial<ApprovalRequestData> | null;
  return data && typeof data.approval_id === "string" ? data.approval_id : null;
};

/**
 * Pending→resolved updates for one approval replace the prior entry in place
 * (same slot), so replay and live streams both end with exactly one card.
 * Any non-approval entry is appended unchanged.
 */
export function upsertApprovalToolData<T extends StreamToolDataEntry>(
  entries: T[],
  entry: T,
): T[] {
  const id = approvalId(entry);
  if (id === null) return [...entries, entry];
  const index = entries.findIndex((e) => approvalId(e) === id);
  if (index < 0) return [...entries, entry];
  return entries.map((e, i) => (i === index ? entry : e));
}
