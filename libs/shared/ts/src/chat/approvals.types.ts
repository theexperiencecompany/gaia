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
  ApprovalDecisionRequest,
  ApprovalRequestEntryData,
  BatchApprovalDecisionRequest,
  HILPreferencesResponse,
  UpdateHILPreferencesRequest,
} from "../api/generated";

export type {
  ActionResult,
  ApprovalDecider,
  ApprovalOutcome,
  BatchApprovalDecisionResponse,
  BatchDecisionItem,
  BatchDecisionOutcome,
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

export type ApprovalDecision = "approve" | "deny";
export type ApprovalScope = "once" | "always_tool";

/** Body of POST /approvals/{id}/decision — one shape for every client. */
export type ApprovalDecisionPayload = ApprovalDecisionRequest;

/** Body of POST /approvals/batch-decision — decide several approvals at once. */
export type BatchApprovalDecisionPayload = BatchApprovalDecisionRequest;

/** One approval card, as the conversation screen draws it from the approval's entries. */
export type ApprovalRequestData = ApprovalRequestEntryData;
