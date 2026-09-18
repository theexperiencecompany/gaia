import type {
  HandoffDecisionResponse,
  LiveViewTokenResponse,
} from "@shared/api/generated";
import { api } from "@/lib/api/typed";
import type { BrowserHandoffDecision } from "@/types/features/browserTaskTypes";

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
  listTasks: () =>
    api.get("/api/v1/browser/tasks", { query: { limit: 50 }, silent: true }),

  deleteTask: (id: string) =>
    api.delete("/api/v1/browser/tasks/{task_id}", {
      path: { task_id: id },
      successMessage: "Task removed",
      errorMessage: "Could not remove this task",
    }),

  listLogins: () => api.get("/api/v1/browser/logins", { silent: true }),

  forgetLogin: (domain: string) =>
    api.delete("/api/v1/browser/logins/{domain}", {
      path: { domain },
      successMessage: "Login forgotten",
      errorMessage: "Could not forget this login",
    }),

  clearLogins: () =>
    api.delete("/api/v1/browser/logins", {
      successMessage: "All saved logins cleared",
      errorMessage: "Could not clear saved logins",
    }),

  /**
   * Mint the single-use code the local `gaia-connect` tool presents when it
   * uploads this user's browser logins. Authorised by the web session; the tool,
   * which has no cookie, authenticates with the code instead.
   */
  mintImportToken: () =>
    api.post("/api/v1/browser/import/token", { silent: true }),

  /**
   * Continue (the user finished the sensitive step in the live browser) or
   * cancel a browser handoff, unblocking the agent that is waiting on it.
   */
  postHandoffDecision: (
    handoffId: string,
    decision: BrowserHandoffDecision,
    message?: string,
  ): Promise<HandoffDecisionResponse> =>
    api.post("/api/v1/browser/handoffs/{handoff_id}/decision", {
      path: { handoff_id: handoffId },
      body: { decision, message },
      silent: true,
    }),

  /**
   * Current status of a handoff. The card polls this while pending so a reload,
   * or a resolution made via chat / another device, is reflected reliably —
   * the server (Redis) is the source of truth, not the streamed snapshot.
   */
  getHandoffStatus: (handoffId: string): Promise<HandoffDecisionResponse> =>
    api.get("/api/v1/browser/handoffs/{handoff_id}", {
      path: { handoff_id: handoffId },
      silent: true,
    }),

  /**
   * Mint a short-lived takeover token for opening this session's live view. The
   * live view is served from a friendly vhost the session cookie can't reach, so
   * the card fetches a token (cookie auth works same-origin to the API) and rides
   * it on the cross-origin socket + page link.
   */
  getLiveViewToken: (sessionId: string): Promise<LiveViewTokenResponse> =>
    api.get("/api/v1/browser/sessions/{session_id}/live-view-token", {
      path: { session_id: sessionId },
      silent: true,
    }),
};
