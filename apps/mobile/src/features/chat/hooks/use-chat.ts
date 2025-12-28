import { useCallback, useEffect, useRef, useState } from "react";
import type { FlatList } from "react-native";
import { chatApi, createConversation, fetchChatStream, type Message } from "../api/chat-api";

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
  isStreaming: boolean;
  newConversationId: string | null;
  flatListRef: React.RefObject<FlatList | null>;
  sendMessage: (text: string) => Promise<void>;
  cancelStream: () => void;
  scrollToBottom: () => void;
  refetch: () => Promise<void>;
}

export function useChat(chatId: string | null): UseChatReturn {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isTyping, setIsTyping] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [newConversationId, setNewConversationId] = useState<string | null>(null);
  const flatListRef = useRef<FlatList>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const streamingResponseRef = useRef<string>("");
  const currentConversationIdRef = useRef<string | null>(chatId);

  // Keep conversation ID ref in sync
  useEffect(() => {
    currentConversationIdRef.current = chatId;
  }, [chatId]);

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
  const fetchMessagesFromServer = useCallback(
    async (conversationId: string) => {
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
    },
    []
  );

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

  /**
   * Cancel the current streaming response
   */
  const cancelStream = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
    setIsTyping(false);
  }, []);

  /**
   * Send a message and stream the response
   */
  const sendMessage = useCallback(
    async (text: string) => {
      if (!chatId) {
        console.warn("Cannot send message without an active chatId");
        return;
      }

      // Cancel any existing stream
      cancelStream();

      // Add user message
      const userMessage: Message = {
        id: Date.now().toString(),
        text,
        isUser: true,
        timestamp: new Date(),
      };

      // Create placeholder for AI message
      const aiMessageId = (Date.now() + 1).toString();
      const aiMessage: Message = {
        id: aiMessageId,
        text: "",
        isUser: false,
        timestamp: new Date(),
      };

      // Update local state and store
      const updatedMessages = [
        ...(chatMessagesStore[chatId] || []),
        userMessage,
        aiMessage,
      ];
      chatMessagesStore[chatId] = updatedMessages;
      setMessages(updatedMessages);
      setIsTyping(true);
      setIsStreaming(true);
      streamingResponseRef.current = "";

      try {
        // For new chats, create a conversation first
        let conversationIdToSend: string | null = null;
        
        console.log("[useChat] chatId:", chatId, "isServerConversation:", isServerConversation(chatId));
        
        if (isServerConversation(chatId)) {
          // Use existing conversation ID
          conversationIdToSend = chatId;
          console.log("[useChat] Using existing conversation:", conversationIdToSend);
        } else {
          // Create a new conversation on the server
          console.log("[useChat] Creating new conversation...");
          const newConversation = await createConversation("New Chat");
          if (newConversation?.conversation_id) {
            conversationIdToSend = newConversation.conversation_id;
            console.log("[useChat] Created new conversation:", conversationIdToSend);
            // Update the cache to use the new conversation ID
            chatMessagesStore[conversationIdToSend] = updatedMessages;
            delete chatMessagesStore[chatId];
            currentConversationIdRef.current = conversationIdToSend;
            // Signal that a new conversation was created (for redirect)
            setNewConversationId(conversationIdToSend);
          }
        }

        // Start streaming
        // Include history + current user message (exclude only the AI placeholder)
        const cacheKey = conversationIdToSend || chatId;
        const messagesForApi = (chatMessagesStore[cacheKey] || []).slice(0, -1);
        
        const controller = await fetchChatStream(
          {
            message: text,
            conversationId: conversationIdToSend,
            messages: messagesForApi,
          },
          {
            onChunk: (chunk) => {
              streamingResponseRef.current += chunk;
              
              console.log("[useChat] onChunk - accumulated text:", streamingResponseRef.current);

              // Update the AI message with accumulated text
              // IMPORTANT: Create new object to trigger React re-render
              setMessages((prev) => {
                const newMessages = prev.map((msg, index) => {
                  // Update the last message if it's from the bot
                  if (index === prev.length - 1 && !msg.isUser) {
                    return { ...msg, text: streamingResponseRef.current };
                  }
                  return msg;
                });
                console.log("[useChat] Updated messages:", newMessages.length, "Last msg text:", newMessages[newMessages.length - 1]?.text?.substring(0, 50));
                return newMessages;
              });
            },
            onMessageComplete: ({ conversationId: newConvId, messageId }) => {
              // Update the AI message with the real message ID
              setMessages((prev) => {
                const newMessages = [...prev];
                const lastMessage = newMessages[newMessages.length - 1];
                if (lastMessage && !lastMessage.isUser) {
                  lastMessage.id = messageId;
                }
                // Update cache
                if (currentConversationIdRef.current) {
                  chatMessagesStore[currentConversationIdRef.current] =
                    newMessages;
                }
                return newMessages;
              });

              // If this was a new chat, update the conversation ID tracking
              if (!conversationIdToSend && newConvId) {
                // Move messages to new conversation ID in cache
                if (chatMessagesStore[chatId]) {
                  chatMessagesStore[newConvId] = chatMessagesStore[chatId];
                  delete chatMessagesStore[chatId];
                }
                fetchedConversations.add(newConvId);
              }
            },
            onDone: () => {
              setIsTyping(false);
              setIsStreaming(false);
              abortControllerRef.current = null;

              // Final cache update
              if (currentConversationIdRef.current) {
                setMessages((prev) => {
                  chatMessagesStore[currentConversationIdRef.current!] = prev;
                  return prev;
                });
              }
            },
            onError: (error) => {
              console.error("Stream error:", error);
              setIsTyping(false);
              setIsStreaming(false);

              // Update AI message with error
              setMessages((prev) => {
                const newMessages = [...prev];
                const lastMessage = newMessages[newMessages.length - 1];
                if (lastMessage && !lastMessage.isUser && !lastMessage.text) {
                  lastMessage.text =
                    "Sorry, I encountered an error. Please try again.";
                }
                return newMessages;
              });
            },
          }
        );

        abortControllerRef.current = controller;
      } catch (error) {
        console.error("Error starting stream:", error);
        setIsTyping(false);
        setIsStreaming(false);
      }
    },
    [chatId, cancelStream, isServerConversation]
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

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
    isStreaming,
    newConversationId,
    flatListRef,
    sendMessage,
    cancelStream,
    scrollToBottom,
    refetch,
  };
}
