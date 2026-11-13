import type { z } from "zod";
import type { DisplayState, EntryFrame, LiveTask } from "../api/generated";
import type { ApprovalEnd } from "../chat/approvals";
import type { TurnAccumulator } from "../chat/turnAccumulator";
import type { ConversationFrameSchema } from "./frames";

export type {
  DisplayState,
  LiveTask,
  Reaction,
  Reply,
  ReplyDeltaFrame,
  StateFrame,
  UserMessage,
  WorkDeltaFrame,
} from "../api/generated";

export type Entry = EntryFrame["entry"];

/** An entry at its position in the log, as an entry frame delivers it. */
export type LoggedEntry = Omit<EntryFrame, "kind">;

export type ConversationFrame = z.infer<typeof ConversationFrameSchema>;
/** One event of the stream: the frame, and the stream id to resume after (null when replayed from the log). */
export interface ConversationStreamEvent {
  streamId: string | null;
  frame: ConversationFrame;
}

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
  /** This device's own approval decisions, shown until the log's ApprovalDecided arrives. */
  pendingDecisions: Readonly<Record<string, ApprovalEnd>>;
  display: DisplayState;
  work: readonly LiveTask[];
  head: number;
}

export type FrameOutcome =
  | { status: "applied"; view: ConversationView }
  | { status: "unknown_seq"; seq: number; view: ConversationView }
  | { status: "index_gap"; expected: number; view: ConversationView };

/** A frame the view could not apply, after which the stream must be reopened from the log. */
export type FrameGap = Exclude<FrameOutcome, { status: "applied" }>;
