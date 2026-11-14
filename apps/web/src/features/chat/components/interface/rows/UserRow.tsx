import {
  type PendingSend,
  SCREEN_ITEM_KIND,
  type ScreenItem,
} from "@shared/conversation";
import { BASE_MESSAGE_SCHEMA } from "@/config/registries/baseMessageRegistry";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
import type { LocalSend } from "@/features/chat/live/liveConversationStore";
import type { OptimisticMessage } from "@/stores/chatStore";
import type { ChatBubbleUserProps } from "@/types/features/chatBubbleTypes";
import type { RowActions, RowLayout } from "./rows";

type UserSideItem = Extract<
  ScreenItem,
  { kind: "user" | "workflow_fired" | "todo_woke" }
>;

/** The user's side of the chat for one row, as the bubble takes it. */
type UserContent = Partial<
  Omit<ChatBubbleUserProps, "onRetry" | "isRetrying">
> & {
  message_id: string;
  text: string;
  retryable: boolean;
};

function itemContent(item: UserSideItem): UserContent {
  switch (item.kind) {
    case SCREEN_ITEM_KIND.USER: {
      const { message } = item;
      return {
        message_id: item.id,
        date: item.at,
        text: message.text,
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
        retryable: true,
      };
    }
    // The run's side of the chat: its card alone, as a message with no text.
    case SCREEN_ITEM_KIND.WORKFLOW_FIRED:
      return {
        message_id: item.id,
        date: item.at,
        text: "",
        selectedWorkflow: item.workflow,
        retryable: false,
      };
    case SCREEN_ITEM_KIND.TODO_WOKE:
      return {
        message_id: item.id,
        date: item.at,
        text: "",
        todo_run_wake: item.wake,
        retryable: false,
      };
    default: {
      const unhandled: never = item;
      return unhandled;
    }
  }
}

const pendingContent = (
  send: PendingSend,
  local: LocalSend | undefined,
): UserContent => ({
  message_id: send.id,
  text: send.text,
  fileIds: local?.body.file_ids ?? [],
  fileData: local?.fileData,
  selectedTool: local?.body.selected_tool,
  toolCategory: local?.body.tool_category,
  selectedWorkflow: local?.body.selected_workflow,
  selectedCalendarEvent: local?.body.selected_calendar_event,
  replyToMessage: local?.body.reply_to_message ?? undefined,
  loading: !local?.failed,
  failed: local?.failed ?? false,
  retryable: true,
});

// A conversation not created yet has nowhere to retry into, so its send offers none.
const optimisticContent = (message: OptimisticMessage): UserContent => ({
  message_id: message.id,
  date: message.createdAt?.toISOString(),
  text: message.content,
  fileIds: message.fileIds,
  fileData: message.fileData,
  selectedTool: message.toolName ?? undefined,
  toolCategory: message.toolCategory ?? undefined,
  selectedWorkflow: message.selectedWorkflow ?? undefined,
  selectedCalendarEvent: message.selectedCalendarEvent ?? undefined,
  replyToMessage: message.replyToMessage ?? undefined,
  failed: message.failed,
  retryable: false,
});

/** Which user-side row to draw: a server item, this device's pending send, or a new conversation's first send. */
export type UserRowSource =
  | { kind: "item"; item: UserSideItem }
  | { kind: "pending"; send: PendingSend; local: LocalSend | undefined }
  | { kind: "optimistic"; message: OptimisticMessage };

function sourceContent(source: UserRowSource): UserContent {
  switch (source.kind) {
    case "item":
      return itemContent(source.item);
    case "pending":
      return pendingContent(source.send, source.local);
    case "optimistic":
      return optimisticContent(source.message);
    default: {
      const unhandled: never = source;
      return unhandled;
    }
  }
}

/** A user-side row: the user's message, the workflow that started a run, or what woke a todo's run. */
export function UserRow({
  source,
  actions,
  layout,
}: Readonly<{
  source: UserRowSource;
  actions: RowActions;
  layout: RowLayout;
}>) {
  const { retryable, ...shown } = sourceContent(source);
  return (
    <ChatBubbleUser
      {...BASE_MESSAGE_SCHEMA}
      {...shown}
      isConvoSystemGenerated={actions.isConvoSystemGenerated}
      onRetry={retryable ? () => actions.onRetry(shown.message_id) : undefined}
      isRetrying={actions.isRetrying}
      hideAvatar={layout.compact}
      fullWidth={layout.compact}
      disableActions={layout.compact}
      isGroupedWithNext={layout.isGroupedWithNext}
      isGroupedWithPrev={layout.isGroupedWithPrev}
    />
  );
}
