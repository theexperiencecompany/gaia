import { create } from "zustand";
import type { Message } from "@/features/chat/api/chat-api";
import type { Conversation } from "@/features/chat/types";

interface StreamingState {
  isTyping: boolean;
  isStreaming: boolean;
  conversationId: string | null;
  progress: string | null; // Current progress message (e.g., "Executing Call Executor...")
}

interface ChatState {
  messagesByConversation: Record<string, Message[]>;
  conversations: Conversation[];
  activeChatId: string | null;
  streamingState: StreamingState;
  fetchedConversations: Set<string>;

  setActiveChatId: (id: string | null) => void;
  setMessages: (conversationId: string, messages: Message[]) => void;
  clearMessages: (conversationId: string) => void;
  updateLastMessage: (conversationId: string, text: string) => void;
  updateLastMessageFollowUp: (
    conversationId: string,
    actions: string[],
  ) => void;
  setStreamingState: (state: Partial<StreamingState>) => void;
  markConversationFetched: (conversationId: string) => void;
  isConversationFetched: (conversationId: string) => boolean;
  clearConversationFetched: (conversationId: string) => void;
  setConversations: (conversations: Conversation[]) => void;
  addConversation: (conversation: Conversation) => void;
  updateConversationTitle: (conversationId: string, title: string) => void;
}

export const useChatStore = create<ChatState>((set, get) => ({
  messagesByConversation: {},
  conversations: [],
  activeChatId: null,
  streamingState: {
    isTyping: false,
    isStreaming: false,
    conversationId: null,
    progress: null,
  },
  fetchedConversations: new Set<string>(),

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

  markConversationFetched: (conversationId) =>
    set((state) => {
      const newSet = new Set(state.fetchedConversations);
      newSet.add(conversationId);
      return { fetchedConversations: newSet };
    }),

  isConversationFetched: (conversationId) => {
    return get().fetchedConversations.has(conversationId);
  },

  clearConversationFetched: (conversationId) =>
    set((state) => {
      const newSet = new Set(state.fetchedConversations);
      newSet.delete(conversationId);
      return { fetchedConversations: newSet };
    }),

  setConversations: (conversations) => set({ conversations }),

  addConversation: (conversation) =>
    set((state) => {
      // Don't add if already exists
      if (state.conversations.some((c) => c.id === conversation.id)) {
        return state;
      }
      // Add to beginning of list (newest first)
      return { conversations: [conversation, ...state.conversations] };
    }),

  updateConversationTitle: (conversationId, title) =>
    set((state) => ({
      conversations: state.conversations.map((c) =>
        c.id === conversationId ? { ...c, title } : c
      ),
    })),
}));
