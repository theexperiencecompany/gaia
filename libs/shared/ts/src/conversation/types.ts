import type { z } from "zod";
import type { TurnAccumulator } from "../chat/turnAccumulator";
import type {
  EntrySchema,
  ReactionSchema,
  ReplySchema,
  UserMessageSchema,
} from "./entries";
import type { ConversationFrameSchema, LiveTaskSchema } from "./frames";

export type Entry = z.infer<typeof EntrySchema>;
export type UserMessage = z.infer<typeof UserMessageSchema>;
export type Reaction = z.infer<typeof ReactionSchema>;
export type Reply = z.infer<typeof ReplySchema>;

/** An entry at its position in the log, as an entry frame delivers it. */
export interface LoggedEntry {
  seq: number;
  at: string;
  entry: Entry;
}

export type ConversationFrame = z.infer<typeof ConversationFrameSchema>;
/** One event of the stream: the frame, and the stream id to resume after (null when replayed from the log). */
export interface ConversationStreamEvent {
  streamId: string | null;
  frame: ConversationFrame;
}
type FrameOf<K extends ConversationFrame["kind"]> = Extract<
  ConversationFrame,
  { kind: K }
>;
export type ReplyDeltaFrame = FrameOf<"reply_delta">;
export type WorkDeltaFrame = FrameOf<"work_delta">;
export type StateFrame = FrameOf<"state">;
export type DisplayState = StateFrame["display"];
export type LiveTask = z.infer<typeof LiveTaskSchema>;

/** What one reply attempt or one task has streamed and the log has not saved yet. */
export type StreamDraft =
  | {
      source: "reply";
      attemptId: string;
      /** Null until the attempt's Reply entry exists. */
      replyId: string | null;
      nextIndex: number;
      content: TurnAccumulator;
    }
  | {
      source: "work";
      taskId: string;
      nextIndex: number;
      content: TurnAccumulator;
    };

/** A message this device sent that the log has not given a seq yet. */
export interface PendingSend {
  id: string;
  text: string;
}

/** Everything a client knows about one conversation, folded from its event stream. */
export interface ConversationView {
  /** Ascending by seq, one entry per seq. */
  entries: readonly LoggedEntry[];
  /** In the order their first delta arrived. */
  drafts: readonly StreamDraft[];
  /** Attempts retracted or settled, and tasks whose cards a settled reply took over. */
  closedAttempts: Readonly<Record<string, true>>;
  closedTasks: Readonly<Record<string, true>>;
  /** In send order. */
  pending: readonly PendingSend[];
  display: DisplayState;
  work: readonly LiveTask[];
  head: number;
}

export type FrameOutcome =
  | { status: "applied"; view: ConversationView }
  | { status: "unknown_seq"; seq: number; view: ConversationView }
  | { status: "index_gap"; expected: number; view: ConversationView };
