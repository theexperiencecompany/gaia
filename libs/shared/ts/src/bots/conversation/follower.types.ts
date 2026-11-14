/** Types of the bot conversation follower: what an adapter gives it, and what it hands back. */

import type { ReplyFile } from "../../api/generated";
import type { PlatformName } from "../types";
import type { ReactionOutcome } from "../utils/reaction-outcome";

/** How a platform shows a reply: streamed into edited messages, or sent once final. */
export interface StreamingOptions {
  editIntervalMs: number;
  streaming: boolean;
  platform: PlatformName;
}

/** A message the follower posted: editable, and deletable where the platform lets a bot unsend. */
export interface SentBubble {
  edit: (text: string) => Promise<void>;
  delete?: () => Promise<void>;
}

/**
 * One conversation's chat on the platform, as the follower sees it. Text arrives
 * already rendered by the platform's markdown converter.
 */
export interface ConversationSurface {
  /** Posts a message; replyTo is a platform message id to answer natively, where the platform can. */
  send: (text: string, replyTo: string | null) => Promise<SentBubble>;
  /** Puts emoji on a platform message, replacing the emoji GAIA put there before. */
  react: (
    platformMessageId: string,
    emoji: string,
    replaces: string | null,
  ) => Promise<ReactionOutcome>;
  /** Starts the platform's typing indicator; the returned function stops it. */
  startTyping: () => () => void;
}

/**
 * The surface a follower renders to: the adapter's chat, plus what the base adapter
 * adds for every platform, files and notices that may arrive outside a reply.
 */
export interface FollowSurface extends ConversationSurface {
  /** Uploads a session artifact a reply carries, addressed by its path under the session's artifacts/. */
  sendFile: (conversationId: string, file: ReplyFile) => Promise<void>;
  /** Sends a notice's rendered bubbles; where proactive messages are restricted they go as one. */
  sendNotice: (bubbles: string[]) => Promise<void>;
}

/** What a follower reports when it closes, for the follow's wide event. */
export interface FollowSummary {
  repliesDelivered: number;
  reactionsPlaced: number;
  noticesDelivered: number;
  filesDelivered: number;
}
