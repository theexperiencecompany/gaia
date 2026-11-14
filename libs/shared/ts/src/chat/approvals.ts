import type {
  ApprovalEnd,
  ApprovalLabels,
} from "../utils/approvalLabels.types";
import type {
  ApprovalRequestData,
  HilMode,
  HilPreferences,
} from "./approvals.types";

export type {
  ApprovalEnd,
  ApprovalLabels,
} from "../utils/approvalLabels.types";
export type {
  ActionResult,
  ApprovalDecider,
  ApprovalDecision,
  ApprovalDecisionPayload,
  ApprovalOutcome,
  ApprovalRequestData,
  ApprovalScope,
  BatchApprovalDecisionPayload,
  BatchApprovalDecisionResponse,
  BatchDecisionItem,
  BatchDecisionOutcome,
  HilMode,
  HilPreferences,
  HilPreferencesUpdate,
} from "./approvals.types";

export const APPROVAL_REQUEST_TOOL_NAME = "approval_request";

export const DEFAULT_HIL_MODE: HilMode = "always_allow";

/** Approve taps on cards older than this re-confirm in place first. */
export const RECONFIRM_AGE_SECONDS = 86400;

/** Seconds since the card was asked, as of now (epoch ms); null when the card carries no time. */
export function approvalAgeSeconds(
  askedAt: string | null | undefined,
  now: number,
): number | null {
  if (!askedAt) return null;
  return Math.max(0, (now - Date.parse(askedAt)) / 1000);
}

/** Compact card age: "asked just now" / "asked 1h ago" / "asked 2d ago". */
export function formatApprovalAge(
  ageSeconds: number | null | undefined,
): string {
  if (ageSeconds == null || ageSeconds < 60) return "asked just now";
  const hours = Math.floor(ageSeconds / 3600);
  if (hours < 1) return `asked ${Math.floor(ageSeconds / 60)}m ago`;
  if (hours < 24) return `asked ${hours}h ago`;
  return `asked ${Math.floor(hours / 24)}d ago`;
}

/** A decided approval — no longer actionable, kept as a receipt. */
export function isSettled(end: ApprovalEnd): boolean {
  return end.outcome != null;
}

/** Pick a card's words from its outcome, decider and action: the one rule every client reads. */
export function approvalLabel<T>(
  end: ApprovalEnd,
  labels: ApprovalLabels<T>,
): T {
  if (end.outcome == null) return labels.pending;
  if (end.outcome === "approved" && end.action)
    return labels.action[end.action];
  if (end.outcome === "approved" && end.decider === "auto")
    return labels.autoApproved;
  return labels.outcome[end.outcome];
}

const OUTCOME_LINES: ApprovalLabels<(data: ApprovalRequestData) => string> = {
  pending: () => "",
  autoApproved: (data) =>
    data.auto_reason?.trim() || "Matched what you asked for",
  outcome: {
    approved: () => "You approved this",
    denied: (data) => data.feedback?.trim() || "You declined this",
    expired: () => "Expired without a response",
    cancelled: () => "Cancelled before you decided",
    withdrawn: () => "Agent withdrew this",
  },
  action: {
    executing: () => "You approved this",
    executed: () => "The approved action ran",
    failed: () => "Approved, but it didn't go through",
    unknown: () => "Outcome unknown",
  },
};

/**
 * Whether a tool needs approval — i.e. is in the gated set the mode acts on.
 * `approvalKey` is the server-issued HIL key, never the tool's display name.
 */
export function toolAsks(
  prefs: HilPreferences | undefined,
  approvalKey: string,
  destructive: boolean,
): boolean {
  return prefs?.tool_overrides?.[approvalKey] ?? destructive;
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

/** One line explaining how a settled approval ended, and what its action did. */
export function approvalOutcomeLabel(data: ApprovalRequestData): string {
  return approvalLabel(data, OUTCOME_LINES)(data);
}
