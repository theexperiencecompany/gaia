import { useCallback, useEffect, useRef, useState } from "react";
import type { FlatList } from "react-native";
import { useShallow } from "zustand/react/shallow";
import { useChatStore } from "@/stores/chat-store";
import { chatApi, fetchChatStream, type Message } from "../api/chat-api";

const EMPTY_MESSAGES: Message[] = [];

export type { Message } from "../api/chat-api";

interface UseChatReturn {
  messages: Message[];
  isTyping: boolean;
  isLoading: boolean;
  progress: string | null;
  conversationId: string | null;
  flatListRef: React.RefObject<FlatList | null>;
  sendMessage: (text: string) => Promise<void>;
  cancelStream: () => void;
  scrollToBottom: () => void;
  refetch: () => Promise<void>;
}

export function useChat(chatId: string | null): UseChatReturn {
  const flatListRef = useRef<FlatList>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const streamingResponseRef = useRef<string>("");
  const activeConvIdRef = useRef<string | null>(chatId);
  const [isLoading, setIsLoading] = useState(false);
  const [currentConversationId, setCurrentConversationId] = useState<
    string | null
  >(chatId);

  // Reset when chatId prop changes
  useEffect(() => {
    setCurrentConversationId(chatId);
    activeConvIdRef.current = chatId;
  }, [chatId]);

  const messages = useChatStore(
    useShallow((state) =>
      currentConversationId
        ? (state.messagesByConversation[currentConversationId] ??
          EMPTY_MESSAGES)
        : EMPTY_MESSAGES,
    ),
  );

  const streamingState = useChatStore(
    useShallow((state) => state.streamingState),
  );
  const isTyping =
    streamingState.isTyping &&
    streamingState.conversationId === currentConversationId;
  const progress =
    streamingState.conversationId === currentConversationId
      ? streamingState.progress
      : null;

  // Fetch messages for existing conversations
  const fetchMessagesFromServer = useCallback(
    async (conversationId: string) => {
      const store = useChatStore.getState();
      if (store.isConversationFetched(conversationId)) return;

      setIsLoading(true);
      try {
        const serverMessages = await chatApi.fetchMessages(conversationId);
        if (serverMessages.length > 0) {
          store.setMessages(conversationId, serverMessages);
          store.markConversationFetched(conversationId);
          await chatApi.markConversationAsRead(conversationId);
        }
      } catch (error) {
        console.error("Error fetching messages:", error);
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (chatId) fetchMessagesFromServer(chatId);
  }, [chatId, fetchMessagesFromServer]);

  const scrollToBottom = useCallback(() => {
    setTimeout(() => flatListRef.current?.scrollToEnd({ animated: true }), 100);
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

      // Use existing conversation ID or create temp key for new chats
      const storeKey = activeConvIdRef.current || `temp-${Date.now()}`;
      activeConvIdRef.current = storeKey;

      if (!currentConversationId) {
        setCurrentConversationId(storeKey);
      }

      const currentMessages = store.messagesByConversation[storeKey] || [];
      store.setMessages(storeKey, [...currentMessages, userMessage, aiMessage]);
      store.setStreamingState({
        isTyping: true,
        isStreaming: true,
        conversationId: storeKey,
      });
      streamingResponseRef.current = "";

      try {
        const controller = await fetchChatStream(
          {
            message: text,
            conversationId: chatId, // null for new, actual ID for existing
            messages: [...currentMessages, userMessage],
          },
          {
            onConversationCreated: (newConvId, userMsgId, botMsgId) => {
              const store = useChatStore.getState();
              const msgs = store.messagesByConversation[storeKey] || [];

              // Update message IDs
              const updatedMsgs = msgs.map((msg, idx) => {
                if (idx === msgs.length - 2) return { ...msg, id: userMsgId };
                if (idx === msgs.length - 1) return { ...msg, id: botMsgId };
                return msg;
              });

              // For new conversations, migrate to real ID
              if (!chatId && newConvId) {
                store.setMessages(newConvId, updatedMsgs);
                store.clearMessages(storeKey);
                store.markConversationFetched(newConvId);
                store.setStreamingState({ conversationId: newConvId });
                activeConvIdRef.current = newConvId;
                setCurrentConversationId(newConvId);
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
                  streamingResponseRef.current,
                );
            },
            onProgress: (message) => {
              console.log("[useChat] onProgress received:", message);
              useChatStore.getState().setStreamingState({ progress: message });
            },
            onFollowUpActions: (actions) => {
              useChatStore
                .getState()
                .updateLastMessageFollowUp(activeConvIdRef.current!, actions);
            },
            onDone: () => {
              useChatStore.getState().setStreamingState({
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
                  "Sorry, I encountered an error. Please try again.",
                );
            },
          },
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
    [chatId, currentConversationId, cancelStream],
  );

  useEffect(() => {
    return () => abortControllerRef.current?.abort();
  }, []);

  const refetch = useCallback(async () => {
    if (chatId) {
      useChatStore.getState().clearConversationFetched(chatId);
      await fetchMessagesFromServer(chatId);
    }
  }, [chatId, fetchMessagesFromServer]);

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
