import type { IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";
import type { MessageType } from "@/types/features/convoTypes";
import fetchDate from "@/utils/date/dateUtils";
import type { StreamContext } from "./types";

// ── Pure factory ─────────────────────────────────────────────────────────────

export const createIMessage = (
  messageId: string,
  conversationId: string,
  content: string,
  role: "user" | "assistant",
  status: IMessage["status"],
  sourceMessage: MessageType,
): IMessage => {
  // Preserve original timestamp from sourceMessage to maintain correct ordering
  // This is critical: messages must be ordered by their creation time, not persist time
  const createdAt = sourceMessage.date
    ? new Date(sourceMessage.date)
    : new Date();

  return {
    id: messageId,
    conversationId,
    content,
    role,
    status,
    createdAt,
    updatedAt: new Date(),
    messageId,
    fileIds: sourceMessage.fileIds,
    fileData: sourceMessage.fileData,
    toolName: sourceMessage.selectedTool ?? null,
    toolCategory: sourceMessage.toolCategory ?? null,
    workflowId: sourceMessage.selectedWorkflow?.id ?? null,
    selectedWorkflow: sourceMessage.selectedWorkflow ?? null,
    selectedCalendarEvent: sourceMessage.selectedCalendarEvent ?? null,
    tool_data: sourceMessage.tool_data ?? null,
    follow_up_actions: sourceMessage.follow_up_actions ?? null,
    image_data: sourceMessage.image_data ?? null,
    memory_data: sourceMessage.memory_data ?? null,
    todo_progress: sourceMessage.todo_progress ?? null,
    pinned: sourceMessage.pinned ?? false,
    isConvoSystemGenerated: sourceMessage.isConvoSystemGenerated ?? false,
    replyToMessageId: sourceMessage.replyToMessage?.id ?? null,
    replyToMessageData: sourceMessage.replyToMessage ?? null,
  };
};

// ── Context-bound helpers ────────────────────────────────────────────────────

export const createMessageHelpers = (ctx: StreamContext) => {
  const { refs } = ctx;

  const updateBotMessage = (overrides: Partial<MessageType>) => {
    try {
      const baseMessage: MessageType = {
        type: "bot",
        message_id: refs.current.botMessage?.message_id || "",
        response: refs.current.accumulatedResponse,
        date: fetchDate(),
        isConvoSystemGenerated: false,
        loading: true,
      };

      // Preserve existing data and merge with new overrides
      refs.current.botMessage = {
        ...baseMessage,
        ...refs.current.botMessage, // Keep existing data
        ...overrides, // Apply new updates
      };
    } catch (error) {
      console.error("Error updating bot message:", error);
    }
  };

  const updateBotMessageInStore = (conversationId: string) => {
    if (!refs.current.botMessage?.message_id) return;

    // Get existing message to preserve createdAt timestamp
    const state = useChatStore.getState();
    const existingMessages = state.messagesByConversation[conversationId] ?? [];
    const existingMessage = existingMessages.find(
      (m) => m.id === refs.current.botMessage?.message_id,
    );

    // Use existing createdAt, or derive from user message + 1ms offset for correct ordering
    let createdAt: Date;
    if (existingMessage?.createdAt) createdAt = existingMessage.createdAt;
    else if (refs.current.userMessage?.date)
      // Bot message should be after user message
      createdAt = new Date(
        new Date(refs.current.userMessage.date).getTime() + 1,
      );
    else if (refs.current.botMessage.date)
      createdAt = new Date(refs.current.botMessage.date);
    else createdAt = new Date();

    const updatedMessage: IMessage = {
      id: refs.current.botMessage.message_id,
      conversationId,
      content: refs.current.accumulatedResponse,
      role: "assistant",
      status: refs.current.botMessage.loading === false ? "sent" : "sending",
      createdAt,
      updatedAt: new Date(),
      messageId: refs.current.botMessage.message_id,
      fileIds: refs.current.botMessage.fileIds,
      fileData: refs.current.botMessage.fileData,
      toolName: refs.current.botMessage.selectedTool ?? null,
      toolCategory: refs.current.botMessage.toolCategory ?? null,
      workflowId: refs.current.botMessage.selectedWorkflow?.id ?? null,
      selectedWorkflow: refs.current.botMessage.selectedWorkflow ?? null,
      selectedCalendarEvent:
        refs.current.botMessage.selectedCalendarEvent ?? null,
      tool_data: refs.current.botMessage.tool_data ?? null,
      follow_up_actions: refs.current.botMessage.follow_up_actions ?? null,
      image_data: refs.current.botMessage.image_data ?? null,
      memory_data: refs.current.botMessage.memory_data ?? null,
      todo_progress: refs.current.botMessage.todo_progress ?? null,
      pinned: refs.current.botMessage.pinned ?? false,
      isConvoSystemGenerated:
        refs.current.botMessage.isConvoSystemGenerated ?? false,
    };

    // Update store directly without DB write during streaming
    useChatStore.getState().addOrUpdateMessage(updatedMessage);
  };

  return { updateBotMessage, updateBotMessageInStore };
};
