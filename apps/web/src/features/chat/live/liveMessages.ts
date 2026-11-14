import {
  type ConversationView,
  replyFailureMessage,
  SCREEN_ITEM_KIND,
  type ScreenItem,
  type ScreenRow,
  type StreamDraft,
  screenRows,
  WORK_STATUS,
} from "@shared/conversation";
import type { TypedToolDataEntry } from "@/config/registries/toolRegistry";
import type { MessageType } from "@/types/features/convoTypes";
import type { LocalSend } from "./liveConversationStore";

const STOPPED_WORK: ReadonlySet<string> = new Set([
  WORK_STATUS.CANCELLED,
  WORK_STATUS.LOST,
]);
const LIVE_WORK: ReadonlySet<string> = new Set([
  WORK_STATUS.RUNNING,
  WORK_STATUS.AWAITING_APPROVAL,
]);
// Far above any one conversation's rows, so a visible row is never evicted.
const MAX_CACHED_ROWS = 2000;

/**
 * Rows keep their object identity while their inputs are unchanged, so the
 * memoized bubbles skip re-rendering on every streamed token of another row.
 */
const rowCache = new Map<string, { inputs: unknown[]; message: MessageType }>();

function stableRow(
  key: string,
  inputs: unknown[],
  build: () => MessageType,
): MessageType {
  const cached = rowCache.get(key);
  if (
    cached &&
    cached.inputs.length === inputs.length &&
    cached.inputs.every((input, at) => Object.is(input, inputs[at]))
  )
    return cached.message;
  const message = build();
  rowCache.delete(key);
  rowCache.set(key, { inputs, message });
  if (rowCache.size > MAX_CACHED_ROWS) {
    const oldest = rowCache.keys().next().value;
    if (oldest !== undefined) rowCache.delete(oldest);
  }
  return message;
}

// The bubble's registry narrows tool entries by name at render.
const cards = (entries: readonly unknown[]) => entries as TypedToolDataEntry[];

function itemRow(item: ScreenItem, draft: StreamDraft | null): MessageType {
  switch (item.kind) {
    case SCREEN_ITEM_KIND.USER: {
      const { message } = item;
      return stableRow(item.id, [item], () => ({
        type: "user",
        response: message.text,
        message_id: item.id,
        seq: item.seq,
        date: item.at,
        fileIds: message.file_ids,
        fileData: message.files,
        selectedTool: message.selected_tool,
        toolCategory: message.tool_category,
        selectedWorkflow: message.selected_workflow,
        selectedCalendarEvent: message.selected_calendar_event,
        replyToMessage: message.reply_to_message ?? undefined,
        reaction: message.reaction,
        pinned: message.pinned,
        todo_run_wake: message.todo_run_wake ?? undefined,
      }));
    }
    case SCREEN_ITEM_KIND.REPLY: {
      const streamed = draft?.content;
      return stableRow(item.id, [item, streamed], () => ({
        type: "bot",
        response: streamed?.responseText ?? item.text,
        message_id: item.id,
        seq: item.seq,
        date: item.at,
        tool_data: cards(streamed?.toolData ?? item.tool_data),
        follow_up_actions: [
          ...(streamed?.followUpActions ?? item.follow_up_actions),
        ],
        image_data: item.image ?? undefined,
        pinned: item.pinned,
        in_progress: item.outcome === null,
        stopped: item.outcome === "stopped",
        // With text shown, the bubble words this as the cut-short strip under it.
        error:
          item.outcome === "failed"
            ? replyFailureMessage(item.failure)
            : undefined,
        replyToMessage: item.quote ?? undefined,
      }));
    }
    case SCREEN_ITEM_KIND.WORK: {
      const streamed = draft?.content.toolData;
      return stableRow(item.id, [item, streamed], () => ({
        type: "bot",
        response: "",
        message_id: item.id,
        seq: item.seq,
        tool_data: cards([
          ...(item.handoff ? [item.handoff] : []),
          ...(streamed ?? item.tool_data),
          ...item.approvals,
        ]),
        image_data: item.image ?? undefined,
        in_progress: LIVE_WORK.has(item.status),
        stopped: STOPPED_WORK.has(item.status),
      }));
    }
    case SCREEN_ITEM_KIND.NOTICE:
      return stableRow(item.id, [item], () => ({
        type: "bot",
        response: item.text,
        message_id: item.id,
        seq: item.seq,
        date: item.at,
        tool_data: cards(item.tool_data),
        follow_up_actions: [...item.follow_up_actions],
      }));
    // The run's side of the chat: its card alone, as a message with no text.
    case SCREEN_ITEM_KIND.WORKFLOW_FIRED:
      return stableRow(item.id, [item], () => ({
        type: "user",
        response: "",
        message_id: item.id,
        seq: item.seq,
        date: item.at,
        selectedWorkflow: item.workflow,
      }));
    case SCREEN_ITEM_KIND.TODO_WOKE:
      return stableRow(item.id, [item], () => ({
        type: "user",
        response: "",
        message_id: item.id,
        seq: item.seq,
        date: item.at,
        todo_run_wake: item.wake,
      }));
    default: {
      const unhandled: never = item;
      return unhandled;
    }
  }
}

function row(
  shown: ScreenRow,
  sends: Readonly<Record<string, LocalSend>>,
): MessageType {
  switch (shown.kind) {
    case "item":
      return itemRow(shown.item, shown.draft);
    case "draft": {
      const { draft } = shown;
      const id = draft.replyId ?? `draft:${draft.attemptId}`;
      return stableRow(`draft:${draft.attemptId}`, [draft.content], () => ({
        type: "bot",
        response: draft.content.responseText,
        message_id: id,
        tool_data: cards(draft.content.toolData),
        follow_up_actions: [...(draft.content.followUpActions ?? [])],
        in_progress: true,
      }));
    }
    case "pending": {
      const send = sends[shown.send.id];
      return stableRow(`pending:${shown.send.id}`, [shown.send, send], () => ({
        type: "user",
        response: shown.send.text,
        message_id: shown.send.id,
        fileIds: send?.body.file_ids ?? [],
        fileData: send?.fileData,
        selectedTool: send?.body.selected_tool,
        toolCategory: send?.body.tool_category,
        selectedWorkflow: send?.body.selected_workflow,
        selectedCalendarEvent: send?.body.selected_calendar_event,
        replyToMessage: send?.body.reply_to_message ?? undefined,
        loading: !send?.failed,
        failed: send?.failed ?? false,
      }));
    }
    default: {
      const unhandled: never = shown;
      return unhandled;
    }
  }
}

/** The chat screen's rows for a live conversation, in the shape the existing bubbles render. */
export function liveMessages(
  view: ConversationView,
  sends: Readonly<Record<string, LocalSend>>,
): MessageType[] {
  return screenRows(view).map((shown) => row(shown, sends));
}
