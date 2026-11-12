import type {
  ApprovalDescription,
  ApprovalRequestData,
  ApprovalStatus,
  HilMode,
  HilPreferences,
} from "./approvals.types";
import type { StreamToolDataEntry } from "./streaming";

export type {
  ApprovalDecision,
  ApprovalDecisionPayload,
  ApprovalDescription,
  ApprovalRequestData,
  ApprovalScope,
  ApprovalStatus,
  BatchApprovalDecisionPayload,
  BatchApprovalDecisionResponse,
  BatchDecisionItem,
  BatchDecisionOutcome,
  HilMode,
  HilPreferences,
  HilPreferencesUpdate,
  PendingApprovalCardData,
  SettledApprovalCardData,
} from "./approvals.types";

export const APPROVAL_REQUEST_TOOL_NAME = "approval_request";

export const DEFAULT_HIL_MODE: HilMode = "auto";

/** Approve taps on cards older than this re-confirm in place first. */
export const RECONFIRM_AGE_SECONDS = 86400;

/** Closing verb for a card saved before the server described it. */
const LEGACY_CONFIRM = "go ahead";

/**
 * Seconds since the card was asked, computed now — never a stored snapshot,
 * which goes stale the moment it is written. Null when the card predates
 * `asked_at` or carries an unreadable one.
 */
export function approvalAgeSeconds(
  data: Pick<ApprovalRequestData, "asked_at">,
  now: number = Date.now(),
): number | null {
  if (!data.asked_at) return null;
  const asked = Date.parse(data.asked_at);
  if (Number.isNaN(asked)) return null;
  return Math.max(0, Math.floor((now - asked) / 1000));
}

/** How long ago, in words: "just now" / "5m ago" / "1h ago" / "2d ago". */
export function formatApprovalAge(ageSeconds: number): string {
  if (ageSeconds < 60) return "just now";
  const hours = Math.floor(ageSeconds / 3600);
  if (hours < 1) return `${Math.floor(ageSeconds / 60)}m ago`;
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** The card's plain-language description; a card saved before descriptions reads as its summary. */
export function cardDescription(
  data: Pick<ApprovalRequestData, "description" | "summary">,
): ApprovalDescription {
  return (
    data.description ?? {
      action: data.summary,
      headline: data.summary,
      confirm: LEGACY_CONFIRM,
      details: [],
    }
  );
}

/** The card's expiry, only while it is pending and only when it really expires. */
export function approvalExpiresAt(data: ApprovalRequestData): string | null {
  return data.status === "pending" ? (data.expires_at ?? null) : null;
}

/** The card settled to `status`; a decision drops any expiry, since a decided card cannot expire. */
export function settleCard(
  data: ApprovalRequestData,
  status: Exclude<ApprovalStatus, "pending">,
  feedback: string | null,
): ApprovalRequestData {
  if (data.status !== "pending") return { ...data, status, feedback };
  const { expires_at: _expiry, ...rest } = data;
  return { ...rest, status, feedback };
}

/** A decided approval — no longer actionable, kept as a receipt. */
export function isSettled(status: ApprovalStatus): boolean {
  return status !== "pending";
}

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

/** One sentence saying what happened to a settled approval, in the user's terms. */
export function approvalOutcomeLabel(data: ApprovalRequestData): string {
  switch (data.status) {
    case "auto_approved":
      return (
        data.auto_reason?.trim() || "GAIA ran this because you asked for it"
      );
    case "approved":
      return "You approved this";
    case "executed":
      return "You approved this, and it's done";
    case "failed":
      return "You approved this, but it didn't go through";
    case "unknown":
      return "You approved this, but GAIA couldn't confirm it went through";
    case "denied":
      return "You declined this";
    case "timeout":
      return "This expired before you answered, so nothing was done";
    case "abandoned":
    case "cancelled":
      return "You stopped GAIA before answering, so nothing was done";
    case "revoked":
      return "GAIA withdrew this request, so nothing was done";
    case "pending":
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
