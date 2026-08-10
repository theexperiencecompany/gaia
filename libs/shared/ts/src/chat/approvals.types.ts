/**
 * The HIL approval contract, shared by every client (web, mobile, bots).
 *
 * Behaviour over these shapes lives in `approvals.ts`.
 */

/**
 * The three global approval modes:
 * - `always_allow` — run every action without asking.
 * - `always_ask` — pause for approval on every destructive action.
 * - `auto` — an intent judge runs actions that match what the user asked for,
 *   and pauses for approval on anything that deviates or is unclear.
 */
export type HilMode = "always_allow" | "always_ask" | "auto";

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

export type ApprovalStatus =
  | "pending"
  | "approved"
  | "denied"
  | "timeout"
  | "abandoned"
  | "auto_approved";

export type ApprovalDecision = "approve" | "deny";
export type ApprovalScope = "once" | "always_tool";

/** Body of POST /approvals/{id}/decision — one shape for every client. */
export interface ApprovalDecisionPayload {
  decision: ApprovalDecision;
  feedback?: string;
  scope?: ApprovalScope;
}

/** One approval's decision within POST /approvals/batch-decision. */
export interface BatchDecisionItem {
  approval_id: string;
  decision: ApprovalDecision;
  feedback?: string;
}

/** Body of POST /approvals/batch-decision — decide several approvals at once. */
export interface BatchApprovalDecisionPayload {
  decisions: BatchDecisionItem[];
}

/** Per-approval outcome of a batch decision. */
export interface BatchDecisionOutcome {
  approval_id: string;
  resolved: boolean;
  reason: string | null;
}

/** Response of POST /approvals/batch-decision. */
export interface BatchApprovalDecisionResponse {
  outcomes: BatchDecisionOutcome[];
}

/** One approval card, as streamed to the client. */
export interface ApprovalRequestData {
  approval_id: string;
  tool_call_id: string;
  gated_tool_name: string;
  integration_name: string | null;
  summary: string;
  args_preview: Record<string, unknown>;
  status: ApprovalStatus;
  feedback: string | null;
  /** Why auto mode ran this without asking. Only set on `auto_approved`. */
  auto_reason?: string | null;
  timeout_seconds: number;
}
