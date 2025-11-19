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

  const convoMessages = useMemo(() => {
    if (!activeConversationId) return [];
    const messages = messagesByConversation[activeConversationId] ?? [];
    return messages.map(mapStoredMessageToConversationMessage);
  }, [activeConversationId, messagesByConversation]);

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
