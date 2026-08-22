"use client";

import type { ApprovalRequestData } from "@shared/chat";
import { createContext, useContext } from "react";

/**
 * Persists a HIL approval decision back into the OWNING message's `tool_data`.
 *
 * The resolved frame is published on the resumed run's stream (a different
 * message), so it never reaches the original card. Without this, a decision
 * lived only in component-local state: the "Waiting for approval" pill (derived
 * from `tool_data`) never cleared and, on reload, the settled card re-rendered as
 * a fresh actionable one. `TextBubble` owns `message_id` + `tool_data`, so it
 * provides the resolver; the approval card consumes it.
 */
export type ApprovalResolver = (
  approvalId: string,
  resolved: ApprovalRequestData,
) => void;

const ApprovalResolveContext = createContext<ApprovalResolver | null>(null);

export const ApprovalResolveProvider = ApprovalResolveContext.Provider;

export function useApprovalResolver(): ApprovalResolver | null {
  return useContext(ApprovalResolveContext);
}
