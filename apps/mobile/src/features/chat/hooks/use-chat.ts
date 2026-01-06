import { useCallback, useEffect, useRef, useState } from "react";
import type { FlashListRef } from "@shopify/flash-list";
import { useShallow } from "zustand/react/shallow";
import { useChatStore } from "@/stores/chat-store";
import { chatApi, fetchChatStream, type Message } from "../api/chat-api";
import {
  useConversationQuery,
  useChatQueryClient,
  chatKeys,
} from "../api/queries";
import { useQueryClient } from "@tanstack/react-query";

const EMPTY_MESSAGES: Message[] = [];

export type { Message } from "../api/chat-api";

interface UseChatOptions {
  onNavigate?: (conversationId: string) => void;
}

interface UseChatReturn {
  messages: Message[];
  isTyping: boolean;
  isLoading: boolean;
  progress: string | null;
  conversationId: string | null;
  flatListRef: React.RefObject<FlashListRef<Message> | null>;
  sendMessage: (text: string) => Promise<void>;
  cancelStream: () => void;
  scrollToBottom: () => void;
  refetch: () => Promise<void>;
}

export function useChat(
  chatId: string | null,
  options?: UseChatOptions
): UseChatReturn {
  const flatListRef = useRef<FlashListRef<Message>>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const streamingResponseRef = useRef<string>("");
  const queryClient = useQueryClient();

  const storeActiveChatId = useChatStore((state) => state.activeChatId);
  const effectiveChatId = chatId ?? storeActiveChatId;

  const activeConvIdRef = useRef<string | null>(effectiveChatId);
  const [currentConversationId, setCurrentConversationId] = useState<
    string | null
  >(effectiveChatId);

  useEffect(() => {
    const newEffectiveId = chatId ?? storeActiveChatId;
    if (newEffectiveId && !newEffectiveId.startsWith("temp-")) {
      setCurrentConversationId(newEffectiveId);
      activeConvIdRef.current = newEffectiveId;
    }
  }, [chatId, storeActiveChatId]);

  const {
    data: cachedMessages,
    isLoading,
    refetch: refetchQuery,
  } = useConversationQuery(currentConversationId);

  const streamingMessages = useChatStore(
    useShallow((state) =>
      currentConversationId
        ? (state.messagesByConversation[currentConversationId] ?? null)
        : null
    )
  );

  const messages = streamingMessages ?? cachedMessages ?? EMPTY_MESSAGES;

  const streamingState = useChatStore(
    useShallow((state) => state.streamingState)
  );

  const isTyping =
    streamingState.isTyping &&
    streamingState.conversationId === currentConversationId;

  const progress =
    streamingState.conversationId === currentConversationId
      ? streamingState.progress
      : null;

  useEffect(() => {
    if (cachedMessages && cachedMessages.length > 0 && currentConversationId) {
      chatApi.markConversationAsRead(currentConversationId);
    }
  }, [cachedMessages, currentConversationId]);

  const scrollToBottom = useCallback(() => {
    flatListRef.current?.scrollToEnd({ animated: true });
  }, []);

  const cancelStream = useCallback(() => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    useChatStore.getState().setStreamingState({
      isStreaming: false,
      isTyping: false,
      conversationId: null,
    });
  }, []);

  const sendMessage = useCallback(
    async (text: string) => {
      cancelStream();
      const store = useChatStore.getState();

      const userMessage: Message = {
        id: `temp-user-${Date.now()}`,
        text,
        isUser: true,
        timestamp: new Date(),
      };

      const aiMessage: Message = {
        id: `temp-ai-${Date.now()}`,
        text: "",
        isUser: false,
        timestamp: new Date(),
      };

      const storeKey = activeConvIdRef.current || `temp-${Date.now()}`;
      activeConvIdRef.current = storeKey;

      if (!currentConversationId) {
        setCurrentConversationId(storeKey);
      }

      const existingMessages =
        store.messagesByConversation[storeKey] ??
        cachedMessages ??
        EMPTY_MESSAGES;

      store.setMessages(storeKey, [...existingMessages, userMessage, aiMessage]);
      store.setStreamingState({
        isTyping: true,
        isStreaming: true,
        conversationId: storeKey,
      });
      streamingResponseRef.current = "";

      try {
        const existingConvId = activeConvIdRef.current;
        const apiConversationId =
          existingConvId && !existingConvId.startsWith("temp-")
            ? existingConvId
            : null;

        const controller = await fetchChatStream(
          {
            message: text,
            conversationId: apiConversationId,
            messages: [...existingMessages, userMessage],
          },
          {
            onConversationCreated: (
              newConvId,
              userMsgId,
              botMsgId,
              description
            ) => {
              const store = useChatStore.getState();
              const msgs = store.messagesByConversation[storeKey] || [];

              const updatedMsgs = msgs.map((msg, idx) => {
                if (idx === msgs.length - 2) return { ...msg, id: userMsgId };
                if (idx === msgs.length - 1) return { ...msg, id: botMsgId };
                return msg;
              });

              if (!chatId && newConvId) {
                store.setMessages(newConvId, updatedMsgs);
                store.clearMessages(storeKey);
                store.setStreamingState({ conversationId: newConvId });
                store.setActiveChatId(newConvId);

                store.addConversation({
                  id: newConvId,
                  title: description || "New conversation",
                  created_at: new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                });

                queryClient.invalidateQueries({
                  queryKey: chatKeys.conversations(),
                });

                activeConvIdRef.current = newConvId;
                setCurrentConversationId(newConvId);
                options?.onNavigate?.(newConvId);
              } else {
                store.setMessages(storeKey, updatedMsgs);
              }
            },
            onChunk: (chunk) => {
              streamingResponseRef.current += chunk;
              useChatStore
                .getState()
                .updateLastMessage(
                  activeConvIdRef.current!,
                  streamingResponseRef.current
                );
            },
            onProgress: (message) => {
              useChatStore.getState().setStreamingState({ progress: message });
            },
            onFollowUpActions: (actions) => {
              useChatStore
                .getState()
                .updateLastMessageFollowUp(activeConvIdRef.current!, actions);
            },
            onDone: () => {
              const finalConvId = activeConvIdRef.current;
              const store = useChatStore.getState();
              const finalMessages = store.messagesByConversation[finalConvId!];

              if (finalMessages && finalConvId) {
                queryClient.setQueryData(
                  chatKeys.messages(finalConvId),
                  finalMessages
                );
                store.clearMessages(finalConvId);
              }

              store.setStreamingState({
                isTyping: false,
                isStreaming: false,
                conversationId: null,
                progress: null,
              });
              abortControllerRef.current = null;
            },
            onError: (error) => {
              console.error("Stream error:", error);
              useChatStore.getState().setStreamingState({
                isTyping: false,
                isStreaming: false,
                conversationId: null,
                progress: null,
              });
              useChatStore
                .getState()
                .updateLastMessage(
                  activeConvIdRef.current!,
                  "Sorry, I encountered an error. Please try again."
                );
            },
          }
        );
        abortControllerRef.current = controller;
      } catch (error) {
        console.error("Error starting stream:", error);
        useChatStore.getState().setStreamingState({
          isTyping: false,
          isStreaming: false,
          conversationId: null,
        });
      }
    },
    [chatId, currentConversationId, cancelStream, cachedMessages, queryClient, options]
  );

  const refetch = useCallback(async () => {
    if (currentConversationId) {
      await refetchQuery();
    }
  }, [currentConversationId, refetchQuery]);

  return {
    messages,
    isTyping,
    isLoading,
    progress,
    conversationId: currentConversationId,
    flatListRef,
    sendMessage,
    cancelStream,
    scrollToBottom,
    refetch,
  };
}
