import { apiService } from "@/lib/api/service";
import type {
  BrowserHandoffDecision,
  BrowserHandoffStatus,
} from "@/types/features/browserTaskTypes";

interface HandoffDecisionResponse {
  handoff_id: string;
  status: BrowserHandoffStatus;
}

interface LiveViewTokenResponse {
  token: string;
  expires_in: number;
}

/**
 * The live-view route serves both a GET page and a WebSocket at the same path;
 * the canvas talks to the WebSocket. The snapshot carries the public HTTP
 * live-view base (`{BROWSER_LIVE_VIEW_BASE_URL}/live/{id}`) — a friendly vhost
 * the host-only session cookie is NOT sent to — so every connection must carry a
 * `?t=` takeover token. The socket URL is the base with the scheme swapped to
 * ws(s) and the token appended.
 */
export function liveViewSocketUrl(
  liveViewHttpUrl: string,
  token: string,
): string {
  const wsUrl = liveViewHttpUrl.replace(/^http/, "ws");
  return `${wsUrl}?t=${encodeURIComponent(token)}`;
}

/** The full-browser page link carries the same token (cookie is cross-origin). */
export function liveViewPageUrl(
  liveViewHttpUrl: string,
  token: string,
): string {
  return `${liveViewHttpUrl}?t=${encodeURIComponent(token)}`;
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

  /**
   * Mint a short-lived takeover token for opening this session's live view. The
   * live view is served from a friendly vhost the session cookie can't reach, so
   * the card fetches a token (cookie auth works same-origin to the API) and rides
   * it on the cross-origin socket + page link.
   */
  getLiveViewToken: async (
    sessionId: string,
  ): Promise<LiveViewTokenResponse | null> => {
    return apiService.get<LiveViewTokenResponse>(
      `/browser/sessions/${sessionId}/live-view-token`,
      { silent: true },
    );
  },
};
