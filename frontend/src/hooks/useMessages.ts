import { useEffect, useMemo, useRef } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import { db, type IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";
import { useConversationStore } from "@/stores/conversationStore";
import { MessageType } from "@/types/features/convoTypes";

interface MessageMetadata {
  originalMessage?: MessageType;
}

const EMPTY_ARRAY: IMessage[] = [];

const createMessagesSelector =
  (conversationId?: string) =>
  (state: ReturnType<typeof useChatStore.getState>): IMessage[] =>
    conversationId
      ? (state.messagesByConversation[conversationId] ?? EMPTY_ARRAY)
      : EMPTY_ARRAY;

const selectSetMessagesForConversation = (
  state: ReturnType<typeof useChatStore.getState>,
) => state.setMessagesForConversation;

export const useMessages = (conversationId?: string) => {
  const messages = useChatStore(
    useMemo(() => createMessagesSelector(conversationId), [conversationId]),
  );
  const setMessagesForConversation = useChatStore(
    selectSetMessagesForConversation,
  );
  const setConversationMessages = useConversationStore(
    (state) => state.setMessages,
  );
  const resetConversationMessages = useConversationStore(
    (state) => state.resetMessages,
  );

  const prevMessagesLengthRef = useRef(0);

  useEffect(() => {
    if (!conversationId) {
      resetConversationMessages();
      return;
    }

    let isActive = true;

    const hydrateMessages = async () => {
      try {
        const cachedMessages =
          await db.getMessagesForConversation(conversationId);
        if (!isActive) return;
        setMessagesForConversation(conversationId, cachedMessages);
      } catch {
        // Ignore cache read errors
      }

      try {
        const apiMessages = await chatApi.fetchMessages(conversationId);
        if (!isActive) return;

        const mappedMessages = mapApiMessages(apiMessages, conversationId);

        try {
          await db.putMessagesBulk(mappedMessages);
        } catch {
          // Ignore persistence errors to keep UI responsive
        }

        if (!isActive) return;

        setMessagesForConversation(conversationId, mappedMessages);
      } catch {
        // Ignore network errors; cache content remains visible
      }
    };

    hydrateMessages();

    return () => {
      isActive = false;
    };
  }, [conversationId, resetConversationMessages, setMessagesForConversation]);

  useEffect(() => {
    if (!conversationId) {
      resetConversationMessages();
      prevMessagesLengthRef.current = 0;
      return;
    }

    if (prevMessagesLengthRef.current === messages.length) return;

    prevMessagesLengthRef.current = messages.length;

    if (messages.length === 0) {
      setConversationMessages([]);
      return;
    }

    setConversationMessages(
      messages.map(mapStoredMessageToConversationMessage),
    );
  }, [
    conversationId,
    messages.length,
    resetConversationMessages,
    setConversationMessages,
  ]);

  return { messages };
};

const mapApiMessages = (
  messages: MessageType[],
  conversationId: string,
): IMessage[] =>
  messages.map((message, index) => {
    const createdAt = message.date ? new Date(message.date) : new Date();
    const role = mapMessageRole(message.type);
    const messageId =
      message.message_id || `${conversationId}-${index}-${createdAt.getTime()}`;

    return {
      id: messageId,
      conversationId,
      content: message.response,
      role,
      status: message.loading ? "sending" : "sent",
      createdAt,
      updatedAt: createdAt,
      messageId: message.message_id,
      fileIds: message.fileIds,
      fileData: message.fileData,
      toolName: message.selectedTool ?? null,
      toolCategory: message.toolCategory ?? null,
      workflowId: message.selectedWorkflow?.id ?? null,
      metadata: {
        originalMessage: message,
      },
    };
  });

const mapStoredMessageToConversationMessage = (
  message: IMessage,
): MessageType => {
  const metadata = (message.metadata ?? {}) as MessageMetadata;
  if (metadata.originalMessage) {
    return metadata.originalMessage;
  }

  return {
    type: mapConversationType(message.role),
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

const mapMessageRole = (
  role: MessageType["type"],
): "user" | "assistant" | "system" => {
  switch (role) {
    case "user":
      return "user";
    case "bot":
      return "assistant";
    default:
      return "system";
  }
};

const mapConversationType = (
  role: ReturnType<typeof mapMessageRole>,
): "user" | "bot" => {
  if (role === "user") return "user";
  return "bot";
};
