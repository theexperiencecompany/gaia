import type { HandoffDecisionResponse } from "@shared/api/generated";
import { useState } from "react";
import type {
  BrowserHandoffDecision,
  BrowserHandoffStatus,
} from "@/types/features/browserTaskTypes";

export type SettledHandoffStatus = Exclude<BrowserHandoffStatus, "pending">;

/** Sends the user's decision through whatever authorizes it on this surface:
 * the web session (chat card, side panel) or the link's code (live page). */
export type PostHandoffDecision = (
  decision: BrowserHandoffDecision,
) => Promise<HandoffDecisionResponse>;

/**
 * The user's answer to one pending handoff.
 *
 * The run itself reports how a handoff resolved (a resolved handoff snapshot on
 * the card's stream), so nothing here polls: the server's answer to our own
 * decision is shown until that snapshot replaces the prompt. A failed decision
 * is toasted by the API client and leaves the choice open to try again.
 */
export function useHandoffDecision(post: PostHandoffDecision) {
  const [decided, setDecided] = useState<BrowserHandoffDecision | null>(null);
  const [settled, setSettled] = useState<SettledHandoffStatus | null>(null);

  const decide = async (decision: BrowserHandoffDecision) => {
    setDecided(decision);
    try {
      const res = await post(decision);
      if (res.status !== "pending") setSettled(res.status);
    } catch {
      setDecided(null);
    }
  };

  return { decide, decided, settled };
}
