import { apiService } from "@/lib/api/service";
import type {
  BrowserHandoffDecision,
  BrowserHandoffStatus,
} from "@/types/features/browserTaskTypes";

interface HandoffDecisionResponse {
  handoff_id: string;
  status: BrowserHandoffStatus;
}

export const browserApi = {
  /**
   * Continue (the user finished the sensitive step in the live browser) or
   * cancel a browser handoff, unblocking the agent that is waiting on it.
   */
  postHandoffDecision: async (
    handoffId: string,
    decision: BrowserHandoffDecision,
  ): Promise<HandoffDecisionResponse | null> => {
    return apiService.post<HandoffDecisionResponse>(
      `/browser/handoffs/${handoffId}/decision`,
      { decision },
      { silent: true },
    );
  },

  /**
   * Current status of a handoff. The card polls this while pending so a reload,
   * or a resolution made via chat / another device, is reflected reliably —
   * the server (Redis) is the source of truth, not the streamed snapshot.
   */
  getHandoffStatus: async (
    handoffId: string,
  ): Promise<HandoffDecisionResponse | null> => {
    return apiService.get<HandoffDecisionResponse>(
      `/browser/handoffs/${handoffId}`,
      { silent: true },
    );
  },
};
