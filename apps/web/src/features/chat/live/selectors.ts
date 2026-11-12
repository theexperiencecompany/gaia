import type { ToolDataEntry } from "@shared/api/generated";
import { extractToolProgressMessage } from "@shared/chat";
import {
  type AttemptDraft,
  CONVERSATION_DISPLAY,
  type ConversationDisplay,
  type ConversationView,
  ENTRY_KIND,
  type LoggedEntry,
  type PendingSend,
  type Reply,
  type UserMessage,
} from "@shared/conversation";

/** One row of the chat screen, in the order visibleBubbles returns them. */
export type LiveBubble =
  | { kind: "user"; key: string; seq: number; message: UserMessage }
  | {
      kind: "reply";
      key: string;
      /** Null while the attempt streams before its Reply entry is appended. */
      seq: number | null;
      replyId: string;
      text: string;
      toolData: readonly ToolDataEntry[];
      followUpActions: readonly string[];
      streaming: boolean;
    }
  | { kind: "notice"; key: string; seq: number; text: string }
  | {
      kind: "work";
      key: string;
      seq: number;
      taskId: string;
      toolData: readonly ToolDataEntry[];
    }
  | { kind: "pending"; key: string; send: PendingSend };

export interface LoadingRow {
  visible: boolean;
  status: ConversationDisplay;
  /** The newest draft's tool progress line, shown under the status. */
  detail: string | null;
}

const newestDraft = (
  drafts: readonly AttemptDraft[],
  matches: (draft: AttemptDraft) => boolean,
): AttemptDraft | undefined => drafts.findLast(matches);

function draftBubble(
  draft: AttemptDraft,
  replyId: string,
  seq: number | null,
): LiveBubble {
  return {
    kind: "reply",
    key: `reply:${replyId}`,
    seq,
    replyId,
    text: draft.content.responseText,
    toolData: draft.content.toolData,
    followUpActions: draft.content.followUpActions ?? [],
    streaming: true,
  };
}

function replyBubble(
  view: ConversationView,
  seq: number,
  entry: Reply,
): LiveBubble {
  const draft = newestDraft(view.drafts, (d) => d.replyId === entry.reply_id);
  if (draft) return draftBubble(draft, entry.reply_id, seq);
  return {
    kind: "reply",
    key: `reply:${entry.reply_id}`,
    seq,
    replyId: entry.reply_id,
    text: entry.text,
    toolData: entry.tool_data,
    followUpActions: entry.follow_up_actions,
    streaming: false,
  };
}

const finishedTasks = (entries: readonly LoggedEntry[]): Set<string> =>
  new Set(
    entries.flatMap(({ entry }) =>
      entry.kind === ENTRY_KIND.WORK_FINISHED ? [entry.task_id] : [],
    ),
  );

function entryBubble(
  view: ConversationView,
  { seq, entry }: LoggedEntry,
  finished: ReadonlySet<string>,
): LiveBubble | null {
  switch (entry.kind) {
    case ENTRY_KIND.USER_MESSAGE:
      return { kind: "user", key: `user:${entry.id}`, seq, message: entry };
    case ENTRY_KIND.REPLY:
      return replyBubble(view, seq, entry);
    case ENTRY_KIND.NOTICE:
      return {
        kind: "notice",
        key: `notice:${entry.id}`,
        seq,
        text: entry.text,
      };
    case ENTRY_KIND.WORK_STARTED: {
      if (finished.has(entry.task_id)) return null;
      const draft = newestDraft(view.drafts, (d) => d.taskId === entry.task_id);
      return {
        kind: "work",
        key: `work:${entry.task_id}`,
        seq,
        taskId: entry.task_id,
        toolData: draft?.content.toolData ?? [],
      };
    }
    default:
      return null;
  }
}

/** The rows the chat screen renders: entries by seq, then drafts with no entry yet, then pending sends. */
export function visibleBubbles(view: ConversationView): LiveBubble[] {
  const finished = finishedTasks(view.entries);
  const replies = new Set(
    view.entries.flatMap(({ entry }) =>
      entry.kind === ENTRY_KIND.REPLY ? [entry.reply_id] : [],
    ),
  );
  const logged = view.entries.flatMap((item) => {
    const bubble = entryBubble(view, item, finished);
    return bubble ? [bubble] : [];
  });
  const unopened = view.drafts.flatMap((draft) =>
    draft.replyId !== null && !replies.has(draft.replyId)
      ? [draftBubble(draft, draft.replyId, null)]
      : [],
  );
  const pending = view.pending.map(
    (send): LiveBubble => ({
      kind: "pending",
      key: `pending:${send.id}`,
      send,
    }),
  );
  return [...logged, ...unopened, ...pending];
}

/** The loading row, from the server's display state and the newest draft's progress only. */
export function loadingRow(view: ConversationView): LoadingRow {
  const visible = view.display !== CONVERSATION_DISPLAY.IDLE;
  const progress = visible
    ? view.drafts
        .at(-1)
        ?.content.toolData.map(extractToolProgressMessage)
        .findLast((message) => message !== null)
    : undefined;
  return { visible, status: view.display, detail: progress ?? null };
}
