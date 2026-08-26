import { create } from "zustand";
import type { Message } from "@/features/chat/api/chat-api";

interface StreamingState {
  isTyping: boolean;
  isStreaming: boolean;
  conversationId: string | null;
  progress: string | null;
  progressToolName: string | null;
}

interface ChatState {
  messagesByConversation: Record<string, Message[]>;
  activeChatId: string | null;
  streamingState: StreamingState;

  setActiveChatId: (id: string | null) => void;
  setMessages: (conversationId: string, messages: Message[]) => void;
  clearMessages: (conversationId: string) => void;
  updateLastMessage: (conversationId: string, text: string) => void;
  updateLastAssistantMessage: (
    conversationId: string,
    updates: Partial<Message>,
  ) => void;
  updateLastMessageFollowUp: (
    conversationId: string,
    actions: string[],
  ) => void;
  setStreamingState: (state: Partial<StreamingState>) => void;
}

export const useChatStore = create<ChatState>((set, _get) => ({
  messagesByConversation: {},
  activeChatId: null,
  streamingState: {
    isTyping: false,
    isStreaming: false,
    conversationId: null,
    progress: null,
    progressToolName: null,
  },
  setActiveChatId: (id) => set({ activeChatId: id }),

  setMessages: (conversationId, messages) =>
    set((state) => ({
      messagesByConversation: {
        ...state.messagesByConversation,
        [conversationId]: messages,
      },
    })),

  clearMessages: (conversationId) =>
    set((state) => {
      const { [conversationId]: _, ...rest } = state.messagesByConversation;
      return { messagesByConversation: rest };
    }),

  updateLastMessage: (conversationId, text) =>
    set((state) => {
      const messages = state.messagesByConversation[conversationId] || [];
      if (messages.length === 0) return state;

      const updatedMessages = [...messages];
      const lastMsg = updatedMessages[updatedMessages.length - 1];
      if (lastMsg && !lastMsg.isUser) {
        updatedMessages[updatedMessages.length - 1] = { ...lastMsg, text };
      }

      return {
        messagesByConversation: {
          ...state.messagesByConversation,
          [conversationId]: updatedMessages,
        },
      };
    }),

  updateLastAssistantMessage: (conversationId, updates) =>
    set((state) => {
      const messages = state.messagesByConversation[conversationId] || [];
      if (messages.length === 0) return state;

      const updatedMessages = [...messages];
      const lastMsg = updatedMessages[updatedMessages.length - 1];
      if (lastMsg && !lastMsg.isUser) {
        updatedMessages[updatedMessages.length - 1] = {
          ...lastMsg,
          ...updates,
        };
      }

      return {
        messagesByConversation: {
          ...state.messagesByConversation,
          [conversationId]: updatedMessages,
        },
      };
    }),

  updateLastMessageFollowUp: (conversationId, actions) =>
    set((state) => {
      const messages = state.messagesByConversation[conversationId] || [];
      if (messages.length === 0) return state;

      const updatedMessages = [...messages];
      const lastMsg = updatedMessages[updatedMessages.length - 1];
      if (lastMsg && !lastMsg.isUser) {
        updatedMessages[updatedMessages.length - 1] = {
          ...lastMsg,
          followUpActions: actions,
        };
      }

      return {
        messagesByConversation: {
          ...state.messagesByConversation,
          [conversationId]: updatedMessages,
        },
      };
    }),

  setStreamingState: (newState) =>
    set((state) => ({
      streamingState: { ...state.streamingState, ...newState },
    })),
}));
