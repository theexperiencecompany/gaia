/** Types of the bot conversation follower: what an adapter gives it, and what it hands back. */

import type {
  ApprovalRequested,
  BotDeliveryReport,
  PartialReply,
  ReplyFile,
} from "../../api/generated";
import type { PlatformName } from "../types";
import type { ReactionOutcome } from "../utils/reaction-outcome";

/** How a platform shows a reply: streamed into edited messages, or sent once final. */
export interface StreamingOptions {
  editIntervalMs: number;
  streaming: boolean;
  platform: PlatformName;
}

/** A message the follower posted, edited in place as its bubble grows. */
export interface SentBubble {
  /** The platform message id, kept in the delivery cursor while the bubble is still being written. */
  id: string;
  edit: (text: string) => Promise<void>;
}

/** A message an earlier follow left mid-bubble: finished by an edit, or deleted where it cannot be edited. */
export interface ReopenedBubble extends SentBubble {
  delete: () => Promise<void>;
}

/**
 * One conversation's chat on the platform, as the follower sees it. Text arrives
 * already rendered by the platform's markdown converter.
 */
export interface ConversationSurface {
  /** Posts a message; replyTo is a platform message id to answer natively, where the platform can. */
  send: (text: string, replyTo: string | null) => Promise<SentBubble>;
  /** A message an earlier follow posted in this chat and left mid-bubble, by its platform id. */
  reopen: (platformMessageId: string) => ReopenedBubble;
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
  /** Sends the image at url (a browser step's screenshot) as a photo with its caption. */
  sendPhoto: (url: string, caption: string) => Promise<void>;
  /** Whether this chat is the user's own: a group is shown no browser progress. */
  privateChat: boolean;
}

/** What a follower reports when it closes, for the follow's wide event. */
export interface FollowSummary {
  repliesDelivered: number;
  reactionsPlaced: number;
  noticesDelivered: number;
  filesDelivered: number;
}

/** How far a follower put its conversation on the platform: every item through delivered_seq, plus partial_reply. */
export type DeliveryCursor = Required<Omit<BotDeliveryReport, "platform">>;

/** Where a follow starts, and where it reports each step of what it delivers. */
export interface FollowStart {
  /** Items at or below it were delivered by an earlier follow. */
  floor: number;
  /** The reply just past the floor that an earlier follow sent only its first bubbles of. */
  partialReply: PartialReply | null;
  record: (cursor: DeliveryCursor) => Promise<void>;
}

/** A followed conversation parked on approvals its follow asked the user about. */
export interface AwaitedDecision {
  conversationId: string;
  approvals: ApprovalRequested[];
}
