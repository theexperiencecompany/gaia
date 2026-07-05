import type { StreamToolDataEntry } from "./streaming";

export const APPROVAL_REQUEST_TOOL_NAME = "approval_request";

/**
 * Per-user HIL preferences. `tool_overrides` maps a tool name to whether it
 * should ask before running, holding only the user's diffs from the default
 * (curated) gating — a tool absent from the map uses its default classification.
 */
export interface HilPreferences {
  enabled: boolean;
  tool_overrides: Record<string, boolean>;
}

export type ApprovalStatus = "pending" | "approved" | "denied" | "timeout";

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
