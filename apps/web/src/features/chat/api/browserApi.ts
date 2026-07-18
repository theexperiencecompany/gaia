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
};
