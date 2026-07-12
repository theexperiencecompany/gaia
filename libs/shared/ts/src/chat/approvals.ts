import type { StreamToolDataEntry } from "./streaming";

export const APPROVAL_REQUEST_TOOL_NAME = "approval_request";

/**
 * The three global approval modes:
 * - `always_allow` — run every action without asking.
 * - `always_ask` — pause for approval on every destructive action.
 * - `auto` — an intent judge runs actions that match what the user asked for,
 *   and pauses for approval on anything that deviates or is unclear.
 */
export type HilMode = "always_allow" | "always_ask" | "auto";
export const DEFAULT_HIL_MODE: HilMode = "always_allow";

/**
 * Per-user HIL preferences. `tool_overrides` defines which tools need approval
 * (tool name -> needs-approval), overriding the default destructive
 * classification; a tool absent from the map uses that default. The same gated
 * set applies in both `always_ask` and `auto` — the mode only decides whether
 * the user is asked or the intent judge decides.
 */
export interface HilPreferences {
  mode: HilMode;
  tool_overrides: Record<string, boolean>;
}

export type ApprovalStatus = "pending" | "approved" | "denied" | "timeout";

export type ApprovalDecision = "approve" | "deny";
export type ApprovalScope = "once" | "always_tool";

/** Body of POST /approvals/{id}/decision — one shape for every client. */
export interface ApprovalDecisionPayload {
  decision: ApprovalDecision;
  feedback?: string;
  scope?: ApprovalScope;
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

export interface ApprovalRequestData {
  approval_id: string;
  tool_call_id: string;
  gated_tool_name: string;
  integration_name: string | null;
  summary: string;
  args_preview: Record<string, unknown>;
  status: ApprovalStatus;
  feedback: string | null;
  timeout_seconds: number;
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
