import type { z } from "zod";
import type { DisplayState, LiveTask, ReplyItem } from "../api/generated";
import type { ScreenItemSchema } from "./entries";

export type {
  DisplayState,
  LiveTask,
  Reaction,
  StateFrame,
  UserMessage,
} from "../api/generated";
export type { ConversationFrame } from "./frames";

/** One item of the screen the server projects from the log, as the stream delivers it. */
export type ScreenItem = z.infer<typeof ScreenItemSchema>;

/** What a reply has streamed so far, as the server split and folded it: its item's content. */
export type ReplyDraft = Readonly<
  Pick<ReplyItem, "bubbles" | "tool_data" | "timeline" | "follow_up_actions">
>;

/** What one reply attempt has streamed and its item does not show yet; work's cards come on its item. */
export interface StreamDraft {
  attemptId: string;
  /** Null until the server names the reply the attempt writes. */
  replyId: string | null;
  nextIndex: number;
  content: ReplyDraft;
}

/** A message this device sent that the server's screen does not show yet. */
export interface PendingSend {
  id: string;
  text: string;
}

/** A client's copy of one conversation's screen: the server's items, what is streaming into them, and its own sends. */
export interface ConversationView {
  /** Ascending by seq; the server's items, never reordered here. */
  items: readonly ScreenItem[];
  /** In the order their first delta arrived. */
  drafts: readonly StreamDraft[];
  /** Attempts, replies and work whose streams ended: a late reply delta is dropped. */
  closed: Readonly<Record<string, true>>;
  /** In send order. */
  pending: readonly PendingSend[];
  display: DisplayState;
  work: readonly LiveTask[];
  /** The head of the last state frame: display and work are as of it. */
  head: number;
  /** The log head the items reflect, which runs ahead of head between a patch and its state frame. */
  screenHead: number;
}

export type FrameOutcome =
  | { status: "applied"; view: ConversationView }
  | { status: "index_gap"; expected: number; view: ConversationView };

/** A frame the view could not apply, after which the stream must be reopened for a fresh screen. */
export type FrameGap = Exclude<FrameOutcome, { status: "applied" }>;
