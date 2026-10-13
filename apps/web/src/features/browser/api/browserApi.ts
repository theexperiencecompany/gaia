import type {
  HandoffDecisionResponse,
  LiveViewTokenResponse,
} from "@shared/api/generated";
import { apiOrigin } from "@/lib/api/client";
import { api } from "@/lib/api/typed";
import type { BrowserHandoffDecision } from "@/types/features/browserTaskTypes";

/**
 * The live-view socket, `/live/{target}` on the API: every surface dials it
 * here. `target` is a session id that the takeover `token` authorizes (chat
 * card, side panel, its full-page link), or a bot link's capability code,
 * which is its own authority (no token).
 */
export function liveSocketUrl(target: string, token: string | null): string {
  const base = `${apiOrigin.replace(/^http/, "ws")}/live/${encodeURIComponent(target)}`;
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
   * Mint a short-lived takeover token for opening this session's live view; the
   * card carries it on the socket and the full-page link. Minted on mount, on a
   * renewal timer and on a socket drop, so never a user action.
   */
  getLiveViewToken: (sessionId: string): Promise<LiveViewTokenResponse> =>
    api.get("/api/v1/browser/sessions/{session_id}/live-view-token", {
      path: { session_id: sessionId },
      silent: true,
      background: true,
    }),
};
