import type { FileData, ToolDataEntry } from "@gaia/shared/api/generated";
import {
  type ConversationView,
  replyFailureMessage,
  SCREEN_ITEM_KIND,
  type ScreenItem,
  type ScreenRow,
  type StreamDraft,
  screenRows,
  WORK_STATUS,
} from "@gaia/shared/conversation";
import type { ApiFileData, Message } from "../api/chat-api";
import type { MobileSend } from "./live-conversation-store";

const RUNNING_WORK: ReadonlySet<string> = new Set([
  WORK_STATUS.RUNNING,
  WORK_STATUS.AWAITING_APPROVAL,
]);
const STOPPED_WORK: ReadonlySet<string> = new Set([
  WORK_STATUS.CANCELLED,
  WORK_STATUS.LOST,
]);

/** The display data of a logged message's attachments, as the bubbles read it. */
export const toApiFileData = (files: readonly FileData[]): ApiFileData[] =>
  files.map((file) => ({
    fileId: file.fileId,
    fileName: file.filename,
    url: file.url,
    contentType: file.type ?? undefined,
  }));

// The accumulator holds the same entries the server's items carry, typed loosely for its own merges.
const cards = (entries: readonly unknown[]) => [...entries] as ToolDataEntry[];

function itemRow(item: ScreenItem, draft: StreamDraft | null): Message {
  const placed = { id: item.id, seq: item.seq, timestamp: new Date(item.at) };
  switch (item.kind) {
    case SCREEN_ITEM_KIND.USER: {
      const { message } = item;
      return {
        ...placed,
        text: message.text,
        isUser: true,
        fileIds: message.file_ids,
        fileData: toApiFileData(message.files),
        replyToMessage: message.reply_to_message ?? null,
        reaction: message.reaction,
        pinned: message.pinned,
        todoRunWake: message.todo_run_wake,
      };
    }
    case SCREEN_ITEM_KIND.REPLY: {
      const streamed = draft?.content;
      return {
        ...placed,
        text: streamed?.responseText ?? item.text,
        isUser: false,
        toolData: cards(streamed?.toolData ?? item.tool_data),
        followUpActions: [
          ...(streamed?.followUpActions ?? item.follow_up_actions),
        ],
        imageData: item.image,
        pinned: item.pinned,
        inProgress: item.outcome === null,
        stopped: item.outcome === "stopped",
        error:
          item.outcome === "failed"
            ? replyFailureMessage(item.failure)
            : undefined,
        replyToMessage: item.quote,
      };
    }
    case SCREEN_ITEM_KIND.WORK:
      return {
        ...placed,
        text: "",
        isUser: false,
        toolData: cards([
          ...(item.handoff ? [item.handoff] : []),
          ...(draft?.content.toolData ?? item.tool_data),
        ]),
        imageData: item.image,
        inProgress: RUNNING_WORK.has(item.status),
        stopped: STOPPED_WORK.has(item.status),
      };
    case SCREEN_ITEM_KIND.NOTICE:
      return {
        ...placed,
        text: item.text,
        isUser: false,
        toolData: cards(item.tool_data),
        followUpActions: [...item.follow_up_actions],
      };
    // The run's side of the chat: its card alone, as a message with no text.
    case SCREEN_ITEM_KIND.WORKFLOW_FIRED:
      return {
        ...placed,
        text: "",
        isUser: true,
        firedWorkflow: item.workflow,
      };
    case SCREEN_ITEM_KIND.TODO_WOKE:
      return { ...placed, text: "", isUser: true, todoRunWake: item.wake };
    default: {
      const unhandled: never = item;
      return unhandled;
    }
  }
}

function row(
  shown: ScreenRow,
  sends: Readonly<Record<string, MobileSend>>,
  now: Date,
): Message {
  switch (shown.kind) {
    case "item":
      return itemRow(shown.item, shown.draft);
    case "draft": {
      const { draft } = shown;
      return {
        id: draft.replyId ?? `draft:${draft.attemptId}`,
        text: draft.content.responseText,
        isUser: false,
        timestamp: now,
        toolData: cards(draft.content.toolData),
        followUpActions: [...(draft.content.followUpActions ?? [])],
        inProgress: true,
      };
    }
    case "pending": {
      const send = sends[shown.send.id];
      return {
        id: shown.send.id,
        text: shown.send.text,
        isUser: true,
        timestamp: send ? new Date(send.sentAt) : now,
        fileIds: send?.body.file_ids ?? [],
        fileData: send?.fileData,
        replyToMessage: send?.body.reply_to_message ?? null,
        inProgress: !send?.failed,
        sendFailed: send?.failed ?? false,
      };
    }
    default: {
      const unhandled: never = shown;
      return unhandled;
    }
  }
}

/** The chat screen's rows for a live conversation, in the shape mobile's bubbles render. */
export function liveMessages(
  view: ConversationView,
  sends: Readonly<Record<string, MobileSend>>,
  now: Date,
): Message[] {
  return screenRows(view).map((shown) => row(shown, sends, now));
}
