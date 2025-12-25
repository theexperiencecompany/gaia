import { useCallback, useEffect, useRef, useState } from "react";
import type { FlatList } from "react-native";
import { chatApi, type Message } from "../api/chat-api";
import { getAIResponse } from "../utils/ai-service";

// Re-export Message type for backwards compatibility
export type { Message } from "../api/chat-api";

// Global store for all chat messages, keyed by chatId
const chatMessagesStore: Record<string, Message[]> = {};

// Track which conversations have been fetched from the server
const fetchedConversations = new Set<string>();

interface UseChatReturn {
  messages: Message[];
  isTyping: boolean;
  isLoading: boolean;
  flatListRef: React.RefObject<FlatList | null>;
  sendMessage: (text: string) => Promise<void>;
  scrollToBottom: () => void;
  refetch: () => Promise<void>;
}

export function useChat(chatId: string | null): UseChatReturn {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const flatListRef = useRef<FlatList>(null);

  /**
   * Check if the chatId is a valid server conversation ID
   * Local new chats start with "chat-" and shouldn't be fetched from server
   */
  const isServerConversation = useCallback((id: string | null): boolean => {
    if (!id) return false;
    // Skip local chat IDs and "new"
    if (id.startsWith("chat-") || id === "new") return false;
    return true;
  }, []);

  // Fetch messages from backend
  const fetchMessagesFromServer = useCallback(async (conversationId: string) => {
    // Only fetch from server if we haven't already
    if (fetchedConversations.has(conversationId)) {
      return;
    }

    setIsLoading(true);
    try {
      const serverMessages = await chatApi.fetchMessages(conversationId);
      if (serverMessages.length > 0) {
        chatMessagesStore[conversationId] = serverMessages;
        setMessages(serverMessages);
        fetchedConversations.add(conversationId);
        
        // Mark as read
        await chatApi.markConversationAsRead(conversationId);
      }
    } catch (error) {
      console.error("Error fetching messages:", error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Load messages when chatId changes
  useEffect(() => {
    if (!chatId) {
      setMessages([]);
      return;
    }

    // Check if we have cached messages
    if (chatMessagesStore[chatId]) {
      setMessages(chatMessagesStore[chatId]);
    } else {
      setMessages([]);
    }

    // Fetch from server only for valid server conversation IDs
    if (isServerConversation(chatId)) {
      fetchMessagesFromServer(chatId);
    }
  }, [chatId, isServerConversation, fetchMessagesFromServer]);

  const scrollToBottom = useCallback(() => {
    if (messages.length > 0) {
      setTimeout(() => {
        flatListRef.current?.scrollToEnd({ animated: true });
      }, 100);
    }
  }, [messages.length]);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!chatId) {
        console.warn("Cannot send message without an active chatId");
        return;
      }

      // Add user message
      const userMessage: Message = {
        id: Date.now().toString(),
        text,
        isUser: true,
        timestamp: new Date(),
      };

      // Update local state and store
      const updatedMessages = [
        ...(chatMessagesStore[chatId] || []),
        userMessage,
      ];
      chatMessagesStore[chatId] = updatedMessages;
      setMessages(updatedMessages);
      setIsTyping(true);

      try {
        // Get AI response with chatId
        const aiResponseText = await getAIResponse(text, chatId);

        const aiMessage: Message = {
          id: (Date.now() + 1).toString(),
          text: aiResponseText,
          isUser: false,
          timestamp: new Date(),
        };

        // Update local state and store
        const finalMessages = [...updatedMessages, aiMessage];
        chatMessagesStore[chatId] = finalMessages;
        setMessages(finalMessages);
      } catch (error) {
        console.error("Error getting AI response:", error);
      } finally {
        setIsTyping(false);
      }
    },
    [chatId]
  );

  // Force refetch from server
  const refetch = useCallback(async () => {
    if (chatId && isServerConversation(chatId)) {
      fetchedConversations.delete(chatId);
      await fetchMessagesFromServer(chatId);
    }
  }, [chatId, isServerConversation, fetchMessagesFromServer]);

  return {
    messages,
    isTyping,
    isLoading,
    flatListRef,
    sendMessage,
    scrollToBottom,
    refetch,
  };
}
