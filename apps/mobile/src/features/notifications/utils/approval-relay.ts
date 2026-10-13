import type { ApprovalDecision } from "@gaia/shared/chat";
import { chatApi } from "@/features/chat/api/chat-api";

export interface RelayNotice {
  title: string;
  body: string;
}

export const APPROVAL_ALREADY_HANDLED: RelayNotice = {
  title: "Approval already handled",
  body: "This approval was settled elsewhere — open GAIA to see what happened.",
};

export const APPROVAL_NOT_SENT: RelayNotice = {
  title: "Approval not sent",
  body: "Your decision didn't go through — open GAIA to retry.",
};

/**
 * Relay a decision tapped in the notification shade; the notice to show, or null when it committed.
 *
 * No row version is sent (a push payload carries none), so a refused commit
 * always means the row already settled — another device, or a delayed tap.
 */
export async function relayApprovalDecision(
  approvalId: string,
  decision: ApprovalDecision,
): Promise<RelayNotice | null> {
  try {
    const outcome = await chatApi.postApprovalDecision(approvalId, {
      decision,
    });
    return outcome.success ? null : APPROVAL_ALREADY_HANDLED;
  } catch {
    return APPROVAL_NOT_SENT;
  }
}
