/**
 * Types for the SSE chat streamer ({@link module:bots/api/chat-stream}).
 *
 * @module
 */
import type { AxiosInstance } from "axios";
import type { ApprovalRequestData } from "../../chat";
import type { BotUserContext } from "../types";

/** Fired when a HIL approval frame arrives (bots render it out-of-band). */
export type ApprovalUpdateHandler = (
  data: ApprovalRequestData,
) => void | Promise<void>;

/**
 * Fired when one assistant message ends.
 *
 * `discarded` means the backend has retracted the text that message streamed —
 * it turned out to be a preamble to a handoff, or a draft the style guard is
 * replacing — and the real reply is the next message. A kept boundary is just
 * as load-bearing: it is the point at which streamed text becomes final, and
 * therefore the last point at which a retraction can still take it back.
 */
export type MessageBoundaryHandler = (
  discarded: boolean,
) => void | Promise<void>;

/**
 * Fired when the backend has something to tell the user outside the assistant's reply —
 * currently the rate-limit notice (rendered as a card on web, dropped by bots).
 *
 * It gets its own frame instead of riding the stream as text: text belongs to whichever
 * assistant message is in flight, and a discarded message (handoff preamble, rewritten draft)
 * would take the notice down with it, leaving the user told nothing.
 */
export type NoticeHandler = (text: string) => void | Promise<void>;

/**
 * The slice of {@link GaiaClient} the streamer needs: the HTTP client, auth
 * header builder, and session-token storage. Passed as an explicit deps object
 * so the streaming logic stays decoupled from the client's private internals.
 */
export interface ChatStreamClient {
  client: AxiosInstance;
  userHeaders(ctx: BotUserContext): Record<string, string>;
  storeSessionToken(ctx: BotUserContext, token: string): void;
  clearSessionToken(ctx: BotUserContext): void;
}

/** End of one assistant message; `discarded` retracts the text it streamed. */
export interface MessageBoundary {
  message_id: string;
  discarded: boolean;
}
