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
import type {
  BatchDecisionItem,
  HILPreferencesResponse,
  PendingApprovalCardData,
  SettledApprovalCardData,
  UpdateHILPreferencesRequest,
} from "../api/generated";

export type {
  ApprovalDescription,
  ApprovalDetail,
  BatchApprovalDecisionResponse,
  BatchDecisionItem,
  BatchDecisionOutcome,
  PendingApprovalCardData,
  SettledApprovalCardData,
} from "../api/generated";

export type HilMode = "always_allow" | "always_ask" | "auto";

/**
 * Per-user HIL preferences. `tool_overrides` maps a HIL tool key to
 * needs-approval, overriding the destructive default. A key is a registry
 * tool's bare name or an MCP tool's `mcp:<integration_id>:<name>`; clients read
 * it from the server (`approval_key`) and send it back unchanged.
 */
export type HilPreferences = HILPreferencesResponse;

/** Body of PUT /approvals/preferences; omitted fields are left unchanged. */
export type HilPreferencesUpdate = UpdateHILPreferencesRequest;

/** Where a card stands; only `pending` is still the user's to decide. */
export type ApprovalStatus = ApprovalRequestData["status"];

export type ApprovalDecision = "approve" | "deny";
export type ApprovalScope = "once" | "always_tool";

/** Body of POST /approvals/{id}/decision — one shape for every client. */
export interface ApprovalDecisionPayload {
  decision: ApprovalDecision;
  feedback?: string;
  scope?: ApprovalScope;
  /** Row version the client rendered; stale v refreshes instead of overwriting. */
  v?: number;
}

/** Body of POST /approvals/batch-decision — decide several approvals at once. */
export interface BatchApprovalDecisionPayload {
  decisions: BatchDecisionItem[];
}

/**
 * One approval card, as streamed to the client. A pending card may carry an
 * expiry (interrupt-path approvals only; ledger approvals never expire); a
 * settled card never does. Cards saved before `description` and `asked_at`
 * existed lack them, so readers go through `cardDescription` / `approvalAge`.
 */
export type ApprovalRequestData =
  | PendingApprovalCardData
  | SettledApprovalCardData;
