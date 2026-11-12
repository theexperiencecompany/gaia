import type { ToolDataEntry } from "@shared/api/generated";
import { extractToolProgressMessage, type TurnAccumulator } from "@shared/chat";
import {
  type ConversationView,
  DISPLAY_STATE,
  type DisplayState,
  ENTRY_KIND,
  type LoggedEntry,
  type PendingSend,
  type Reaction,
  type Reply,
  type StreamDraft,
  type UserMessage,
} from "@shared/conversation";

type WorkOutcome = "done" | "failed" | "cancelled" | "lost";
export type WorkStatus = "running" | "awaiting_approval" | WorkOutcome;

/** One row of the chat screen, in the order visibleBubbles returns them. */
export type LiveBubble =
  | {
      kind: "user";
      key: string;
      seq: number;
      message: UserMessage;
      reaction: Reaction | null;
    }
  | {
      kind: "reply";
      key: string;
      /** Null while the attempt streams before its Reply entry is appended. */
      seq: number | null;
      replyId: string | null;
      text: string;
      toolData: readonly ToolDataEntry[];
      followUpActions: readonly string[];
      streaming: boolean;
    }
  | { kind: "notice"; key: string; seq: number; text: string }
  | {
      kind: "work";
      key: string;
      /** Null when the task's WorkStarted entry is not in the view. */
      seq: number | null;
      taskId: string;
      status: WorkStatus;
      toolData: readonly ToolDataEntry[];
    }
  | { kind: "pending"; key: string; send: PendingSend };

export interface LoadingRow {
  visible: boolean;
  status: DisplayState;
  /** The newest draft's tool progress line, shown under the status. */
  detail: string | null;
}

type ReplyDraft = Extract<StreamDraft, { source: "reply" }>;
type WorkDraft = Extract<StreamDraft, { source: "work" }>;

const isReplyDraft = (draft: StreamDraft): draft is ReplyDraft =>
  draft.source === "reply";
const isWorkDraft = (draft: StreamDraft): draft is WorkDraft =>
  draft.source === "work";

const draftContent = (content: TurnAccumulator) => ({
  text: content.responseText,
  toolData: content.toolData,
  followUpActions: content.followUpActions ?? [],
});

function replyBubble(
  view: ConversationView,
  seq: number,
  entry: Reply,
): LiveBubble {
  const draft = view.drafts
    .filter(isReplyDraft)
    .find((d) => d.attemptId === entry.attempt_id);
  const content = draft
    ? draftContent(draft.content)
    : {
        text: entry.text,
        toolData: entry.tool_data,
        followUpActions: entry.follow_up_actions,
      };
  return {
    kind: "reply",
    key: `reply:${entry.reply_id}`,
    seq,
    replyId: entry.reply_id,
    ...content,
    streaming: draft !== undefined,
  };
}

function entryBubble(
  view: ConversationView,
  { seq, entry }: LoggedEntry,
): LiveBubble | null {
  switch (entry.kind) {
    case ENTRY_KIND.USER_MESSAGE:
      return {
        kind: "user",
        key: `user:${entry.id}`,
        seq,
        message: entry,
        reaction: entry.reaction,
      };
    case ENTRY_KIND.REPLY:
      return replyBubble(view, seq, entry);
    case ENTRY_KIND.NOTICE:
      return {
        kind: "notice",
        key: `notice:${entry.id}`,
        seq,
        text: entry.text,
      };
    default:
      return null;
  }
}

function workStatus(view: ConversationView, taskId: string): WorkStatus {
  const finished = view.entries.find(
    ({ entry }) =>
      entry.kind === ENTRY_KIND.WORK_FINISHED && entry.task_id === taskId,
  )?.entry;
  if (finished?.kind === ENTRY_KIND.WORK_FINISHED) return finished.outcome;
  const live = view.work.find((task) => task.task_id === taskId);
  return live?.awaiting_approval ? "awaiting_approval" : "running";
}

// C2: one bubble per live task and per task whose cards no settled reply has taken over yet.
function workBubbles(view: ConversationView): LiveBubble[] {
  const drafts = view.drafts.filter(isWorkDraft);
  const taskIds = [
    ...new Set([
      ...view.work.map((task) => task.task_id),
      ...drafts.map((draft) => draft.taskId),
    ]),
  ];
  return taskIds.map((taskId) => ({
    kind: "work",
    key: `work:${taskId}`,
    seq:
      view.entries.find(
        ({ entry }) =>
          entry.kind === ENTRY_KIND.WORK_STARTED && entry.task_id === taskId,
      )?.seq ?? null,
    taskId,
    status: workStatus(view, taskId),
    toolData:
      drafts.find((draft) => draft.taskId === taskId)?.content.toolData ?? [],
  }));
}

const seqOf = (bubble: LiveBubble): number | null =>
  bubble.kind === "pending" ? null : bubble.seq;

/** The rows the chat screen renders: by seq, then drafts with no entry yet, then pending sends. */
export function visibleBubbles(view: ConversationView): LiveBubble[] {
  const opened = new Set(
    view.entries.flatMap(({ entry }) =>
      entry.kind === ENTRY_KIND.REPLY ? [entry.attempt_id] : [],
    ),
  );
  const unopened = view.drafts.flatMap((draft): LiveBubble[] =>
    isReplyDraft(draft) && !opened.has(draft.attemptId)
      ? [
          {
            kind: "reply",
            key: `draft:${draft.attemptId}`,
            seq: null,
            replyId: draft.replyId,
            ...draftContent(draft.content),
            streaming: true,
          },
        ]
      : [],
  );
  const placed = [
    ...view.entries.flatMap((logged) => entryBubble(view, logged) ?? []),
    ...workBubbles(view),
  ];
  const bySeq = placed.filter((bubble) => seqOf(bubble) !== null);
  bySeq.sort((a, b) => (seqOf(a) ?? 0) - (seqOf(b) ?? 0));
  const pending = view.pending.map(
    (send): LiveBubble => ({
      kind: "pending",
      key: `pending:${send.id}`,
      send,
    }),
  );
  return [
    ...bySeq,
    ...placed.filter((bubble) => seqOf(bubble) === null),
    ...unopened,
    ...pending,
  ];
}

/** The loading row, from the server's display state and the newest draft's progress only. */
export function loadingRow(view: ConversationView): LoadingRow {
  const visible = view.display !== DISPLAY_STATE.IDLE;
  const progress = visible
    ? view.drafts
        .at(-1)
        ?.content.toolData.map(extractToolProgressMessage)
        .findLast((message) => message !== null)
    : undefined;
  return { visible, status: view.display, detail: progress ?? null };
}

/** The user message a settled reply visibly points at, as the server chose it. */
export function quoteFor(
  view: ConversationView,
  replyId: string,
): string | null {
  const settled = view.entries.find(
    ({ entry }) =>
      entry.kind === ENTRY_KIND.REPLY_SETTLED && entry.reply_id === replyId,
  )?.entry;
  return settled?.kind === ENTRY_KIND.REPLY_SETTLED
    ? settled.quote_target
    : null;
}
