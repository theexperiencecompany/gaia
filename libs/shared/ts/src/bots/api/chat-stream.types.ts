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
 * Fired when the backend retracts the assistant message currently on screen —
 * its text turned out to be a preamble to a handoff, and the real reply is the
 * next message.
 */
export type DiscardMessageHandler = () => void | Promise<void>;

/**
 * Fired when the backend has something to tell the user that is NOT part of the
 * assistant's reply — currently the rate-limit notice, which the web renders as
 * a card the bots drop.
 *
 * It gets its own frame rather than riding the stream as text because text
 * belongs to whichever assistant message is in flight: a discarded message (a
 * handoff preamble, a rewritten draft) took the notice down with it, and the
 * user hit a limit and was told nothing.
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
