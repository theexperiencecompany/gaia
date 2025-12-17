/**
 * useChat Hook
 * Manages chat state and message handling per chatId
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { FlatList } from "react-native";
import { getAIResponse } from "../services/ai-service";
import type { Message } from "../types";

// Global store for all chat messages, keyed by chatId
const chatMessagesStore: Record<string, Message[]> = {};

export function useChat(chatId: string | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const flatListRef = useRef<FlatList>(null);

  // Load messages for the current chatId
  useEffect(() => {
    if (chatId) {
      const chatMessages = chatMessagesStore[chatId] || [];
      setMessages(chatMessages);
    } else {
      setMessages([]);
    }
  }, [chatId]);

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
    [chatId],
  );

  return {
    messages,
    isTyping,
    flatListRef,
    sendMessage,
    scrollToBottom,
  };
}
