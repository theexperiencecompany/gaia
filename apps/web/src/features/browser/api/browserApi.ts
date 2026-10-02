import type {
  HandoffDecisionResponse,
  LiveViewTokenResponse,
} from "@shared/api/generated";
import { apiOrigin } from "@/lib/api/client";
import { api } from "@/lib/api/typed";
import type { BrowserHandoffDecision } from "@/types/features/browserTaskTypes";

/**
 * The live-view route serves a WebSocket at `/live/{id}`; the canvas talks to
 * it. The snapshot carries the public HTTP live-view base
 * (`{BROWSER_LIVE_VIEW_BASE_URL}/live/{id}`) — a friendly vhost the host-only
 * session cookie is NOT sent to — so every connection must carry a `?t=`
 * takeover token. The socket URL is the base with the scheme swapped to ws(s)
 * and the token appended.
 */
export function liveViewSocketUrl(
  liveViewHttpUrl: string,
  token: string,
): string {
  const wsUrl = liveViewHttpUrl.replace(/^http/, "ws");
  return `${wsUrl}?t=${encodeURIComponent(token)}`;
}

/**
 * The socket the full-page live view dials: `/live/{code}` on the API, where
 * `code` is the bot link's capability code (it is the authority) or a session
 * id that a takeover token in `token` authorizes.
 */
export function livePageSocketUrl(code: string, token: string | null): string {
  const base = `${apiOrigin.replace(/^http/, "ws")}/live/${encodeURIComponent(code)}`;
  return token ? `${base}?t=${encodeURIComponent(token)}` : base;
}

/** The web's full-page live view of a session, carrying the token its socket needs. */
export function livePagePath(sessionId: string, token: string): string {
  return `/live/${encodeURIComponent(sessionId)}?t=${encodeURIComponent(token)}`;
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
   * stop the browser task, unblocking the agent that is waiting on it.
   */
  postHandoffDecision: (
    handoffId: string,
    decision: BrowserHandoffDecision,
  ): Promise<HandoffDecisionResponse> =>
    api.post("/api/v1/browser/handoffs/{handoff_id}/decision", {
      path: { handoff_id: handoffId },
      body: { decision },
      errorMessage: "Could not send your answer to the browser task",
    }),

  /**
   * Done or Stop from the full-page live view a bot link opened: the link's
   * code authorizes it, so no web session is needed.
   */
  postLiveDecision: (
    code: string,
    decision: BrowserHandoffDecision,
  ): Promise<HandoffDecisionResponse> =>
    api.post("/live/{code}/decision", {
      path: { code },
      body: { decision },
      errorMessage: "Could not send your answer to the browser task",
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
