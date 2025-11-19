import { useMemo } from "react";

import { useChatStore } from "@/stores/chatStore";
import { MessageType } from "@/types/features/convoTypes";

interface MessageMetadata {
  originalMessage?: MessageType;
}

const mapStoredMessageToConversationMessage = (message: any): MessageType => {
  const metadata = (message.metadata ?? {}) as MessageMetadata;
  if (metadata.originalMessage) {
    return metadata.originalMessage;
  }

  return {
    type: message.role === "user" ? "user" : "bot",
    response: message.content,
    message_id: message.messageId ?? message.id,
    date: message.createdAt?.toISOString(),
    fileIds: message.fileIds,
    fileData: message.fileData,
    selectedTool: message.toolName ?? undefined,
    toolCategory: message.toolCategory ?? undefined,
    selectedWorkflow: undefined,
    loading: message.status === "sending",
  } as MessageType;
};

export const useConversation = () => {
  const activeConversationId = useChatStore(
    (state) => state.activeConversationId,
  );
  const messagesByConversation = useChatStore(
    (state) => state.messagesByConversation,
  );
  // Get optimistic messages for new conversations (before conversation ID exists)
  const optimisticMessages = useChatStore((state) => state.optimisticMessages);

  const convoMessages = useMemo(() => {
    // For new conversations (no active conversation ID), show only optimistic messages
    if (!activeConversationId) {
      // Map optimistic messages to MessageType format for UI display
      return optimisticMessages.map((optMsg): MessageType => {
        const metadata = (optMsg.metadata ?? {}) as MessageMetadata;
        if (metadata.originalMessage) {
          return metadata.originalMessage;
        }

        return {
          type: optMsg.role === "user" ? "user" : "bot",
          response: optMsg.content,
          message_id: optMsg.id,
          date: optMsg.createdAt?.toISOString(),
          fileIds: optMsg.fileIds,
          fileData: optMsg.fileData,
          selectedTool: optMsg.toolName ?? undefined,
          toolCategory: optMsg.toolCategory ?? undefined,
          selectedWorkflow: undefined,
          loading: false,
        } as MessageType;
      });
    }

    // For existing conversations, get messages from IndexedDB (via chatStore)
    const messages = messagesByConversation[activeConversationId] ?? [];
    return messages.map(mapStoredMessageToConversationMessage);
  }, [activeConversationId, messagesByConversation, optimisticMessages]);

  const updateConvoMessages = (
    updater: MessageType[] | ((oldMessages: MessageType[]) => MessageType[]),
  ): void => {
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
