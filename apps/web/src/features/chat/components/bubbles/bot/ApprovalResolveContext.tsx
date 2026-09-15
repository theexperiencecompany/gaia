"use client";

import type { ApprovalRequestData } from "@shared/chat";
import { createContext, useContext } from "react";

/**
 * Persists a HIL approval decision back into the OWNING message's `tool_data`.
 *
 * The resolved frame publishes on the resumed run's stream (a different
 * message), so it never reaches the original card. Without this, a decision
 * lived only in local state — the "Waiting for approval" pill never cleared,
 * and reload re-rendered a settled card as fresh. `TextBubble` owns
 * `message_id`+`tool_data` and provides this resolver.
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
