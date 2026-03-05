import { useMemo } from "react";

import type { IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";
import type { MessageType } from "@/types/features/convoTypes";

const mapStoredMessageToConversationMessage = (
  message: IMessage,
): MessageType => {
  return {
    type: message.role === "user" ? "user" : "bot",
    response: message.content,
    message_id: message.messageId ?? message.id,
    date: message.createdAt?.toISOString(),
    fileIds: message.fileIds,
    fileData: message.fileData,
    selectedTool: message.toolName ?? undefined,
    toolCategory: message.toolCategory ?? undefined,
    selectedWorkflow: message.selectedWorkflow ?? undefined,
    selectedCalendarEvent: message.selectedCalendarEvent ?? undefined,
    loading: message.status === "sending",
    tool_data: message.tool_data ?? undefined,
    follow_up_actions: message.follow_up_actions ?? undefined,
    image_data: message.image_data ?? undefined,
    memory_data: message.memory_data ?? undefined,
    todo_progress: message.todo_progress ?? undefined,
    pinned: message.pinned ?? undefined,
    isConvoSystemGenerated: message.isConvoSystemGenerated ?? undefined,
    replyToMessage: message.replyToMessageData ?? undefined,
  } as MessageType;
};

export const useConversation = () => {
  const activeConversationId = useChatStore(
    (state) => state.activeConversationId,
  );
  const messagesByConversation = useChatStore(
    (state) => state.messagesByConversation,
  );
  // Get single optimistic message for new conversations (before conversation ID exists)
  const optimisticMessage = useChatStore((state) => state.optimisticMessage);

  const convoMessages = useMemo(() => {
    // Get messages from IndexedDB for the active conversation
    const dbMessages = activeConversationId
      ? (messagesByConversation[activeConversationId] ?? [])
      : [];

    // Convert IndexedDB messages to MessageType
    const messages = dbMessages.map(mapStoredMessageToConversationMessage);

    // Only add optimistic message for NEW conversations (no activeConversationId)
    // For existing conversations, messages are already in IndexedDB with optimistic flag
    if (
      optimisticMessage &&
      !activeConversationId &&
      optimisticMessage.conversationId === null
    ) {
      const optimisticMsg: MessageType = {
        type:
          optimisticMessage.role === "user"
            ? ("user" as const)
            : ("bot" as const),
        response: optimisticMessage.content,
        message_id: optimisticMessage.id,
        date: optimisticMessage.createdAt?.toISOString(),
        fileIds: optimisticMessage.fileIds,
        fileData: optimisticMessage.fileData,
        selectedTool: optimisticMessage.toolName ?? undefined,
        toolCategory: optimisticMessage.toolCategory ?? undefined,
        selectedWorkflow: undefined,
        loading: false,
      };

      return [...messages, optimisticMsg];
    }

    return messages;
  }, [activeConversationId, messagesByConversation, optimisticMessage]);

  const updateConvoMessages = (): void => {
    console.warn(
      "updateConvoMessages is deprecated. Use IndexedDB directly via chatStore.",
    );
  };

  const clearMessages = (): void => {
    console.warn(
      "clearMessages is deprecated. Use IndexedDB directly via chatStore.",
    );
  };

  return {
    convoMessages,
    updateConvoMessages,
    clearMessages,
  };
};
