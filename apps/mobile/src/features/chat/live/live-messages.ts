import type { FileData } from "@gaia/shared/api/generated";
import {
  type ConversationView,
  ENTRY_KIND,
  type LiveBubble,
  quoteFor,
  replyFailureMessage,
  type UserMessage,
  visibleBubbles,
  type WorkStatus,
} from "@gaia/shared/conversation";
import {
  type ApprovalVerdicts,
  withVerdicts,
} from "@gaia/shared/conversation/live";
import type { ApiFileData, Message, ReplyToMessageData } from "../api/chat-api";
import type { MobileSend } from "./live-conversation-store";

const RUNNING_WORK: ReadonlySet<WorkStatus> = new Set([
  "running",
  "awaiting_approval",
]);
const STOPPED_WORK: ReadonlySet<WorkStatus> = new Set(["cancelled", "lost"]);

/** The display data of a logged message's attachments, as the bubbles read it. */
export const toApiFileData = (files: readonly FileData[]): ApiFileData[] =>
  files.map((file) => ({
    fileId: file.fileId,
    fileName: file.filename,
    url: file.url,
    contentType: file.type ?? undefined,
  }));

interface RowContext {
  view: ConversationView;
  sends: Readonly<Record<string, MobileSend>>;
  userMessages: ReadonlyMap<string, UserMessage>;
  dates: ReadonlyMap<number, Date>;
  verdicts: ApprovalVerdicts;
  /** For rows with no seq yet: a streaming draft that opened no entry. */
  now: Date;
}

function quoted(
  userMessages: ReadonlyMap<string, UserMessage>,
  id: string | null,
): ReplyToMessageData | null {
  const message = id ? userMessages.get(id) : undefined;
  return message
    ? { id: message.id, content: message.text, role: "user" }
    : null;
}

function settlement(view: ConversationView, replyId: string | null) {
  if (!replyId) return null;
  const settled = view.entries.find(
    ({ entry }) =>
      entry.kind === ENTRY_KIND.REPLY_SETTLED && entry.reply_id === replyId,
  )?.entry;
  return settled?.kind === ENTRY_KIND.REPLY_SETTLED ? settled : null;
}

const dateOf = (context: RowContext, seq: number | null): Date =>
  (seq === null ? undefined : context.dates.get(seq)) ?? context.now;

function rowFor(bubble: LiveBubble, context: RowContext): Message {
  const { view, sends, userMessages } = context;
  switch (bubble.kind) {
    case "user": {
      const { message } = bubble;
      return {
        id: bubble.messageId,
        seq: bubble.seq,
        text: message.text,
        isUser: true,
        timestamp: dateOf(context, bubble.seq),
        fileIds: message.file_ids,
        fileData: toApiFileData(message.files),
        replyToMessage:
          message.reply_to_message ?? quoted(userMessages, message.reply_to),
        reaction: bubble.reaction,
        pinned: message.pinned,
        todoRunWake: message.todo_run_wake,
      };
    }
    case "pending": {
      const send = sends[bubble.send.id];
      return {
        id: bubble.messageId,
        text: bubble.send.text,
        isUser: true,
        timestamp: send ? new Date(send.sentAt) : context.now,
        fileIds: send?.body.file_ids ?? [],
        fileData: send?.fileData,
        replyToMessage: send?.body.reply_to_message ?? null,
        inProgress: !send?.failed,
        sendFailed: send?.failed ?? false,
      };
    }
    case "reply": {
      const settled = settlement(view, bubble.replyId);
      return {
        id: bubble.messageId,
        seq: bubble.seq ?? undefined,
        text: bubble.text,
        isUser: false,
        timestamp: dateOf(context, bubble.seq),
        toolData: withVerdicts(bubble.toolData, context.verdicts),
        followUpActions: [...bubble.followUpActions],
        imageData: bubble.image,
        pinned: bubble.pinned,
        inProgress: bubble.streaming,
        stopped: settled?.outcome === "stopped",
        error:
          settled?.outcome === "failed"
            ? replyFailureMessage(settled.failure)
            : undefined,
        replyToMessage: bubble.replyId
          ? quoted(userMessages, quoteFor(view, bubble.replyId))
          : null,
      };
    }
    case "work":
      return {
        id: bubble.messageId,
        seq: bubble.seq ?? undefined,
        text: "",
        isUser: false,
        timestamp: dateOf(context, bubble.seq),
        toolData: withVerdicts(bubble.toolData, context.verdicts),
        inProgress: RUNNING_WORK.has(bubble.status),
        stopped: STOPPED_WORK.has(bubble.status),
      };
    case "notice":
      return {
        id: bubble.messageId,
        seq: bubble.seq ?? undefined,
        text: bubble.text,
        isUser: false,
        timestamp: dateOf(context, bubble.seq),
        toolData: withVerdicts(bubble.toolData, context.verdicts),
      };
    // The run's side of the chat: its card alone, as a message with no text.
    case "workflow_fired":
      return {
        id: bubble.messageId,
        seq: bubble.seq ?? undefined,
        text: "",
        isUser: true,
        timestamp: dateOf(context, bubble.seq),
        firedWorkflow: bubble.workflow,
      };
    case "todo_woke":
      return {
        id: bubble.messageId,
        seq: bubble.seq ?? undefined,
        text: "",
        isUser: true,
        timestamp: dateOf(context, bubble.seq),
        todoRunWake: bubble.wake,
      };
    default: {
      const unhandled: never = bubble;
      return unhandled;
    }
  }
}

/** The chat screen's rows for a live conversation, in the shape mobile's bubbles render. */
export function liveMessages(
  view: ConversationView,
  sends: Readonly<Record<string, MobileSend>>,
  now: Date,
  verdicts: ApprovalVerdicts = {},
): Message[] {
  const userMessages = new Map<string, UserMessage>();
  const dates = new Map<number, Date>();
  for (const { seq, at, entry } of view.entries) {
    dates.set(seq, new Date(at));
    if (entry.kind === ENTRY_KIND.USER_MESSAGE)
      userMessages.set(entry.id, entry);
  }
  const context = { view, sends, userMessages, dates, now, verdicts };
  return visibleBubbles(view).map((bubble) => rowFor(bubble, context));
}
