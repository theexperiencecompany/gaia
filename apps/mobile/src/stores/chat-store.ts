import { create } from "zustand";
import type { Message } from "@/features/chat/api/chat-api";
import type { Conversation } from "@/features/chat/types/index";
import { chatDb } from "@/lib/db/chatDb";

interface StreamingState {
  isTyping: boolean;
  isStreaming: boolean;
  conversationId: string | null;
  progress: string | null;
  progressToolName: string | null;
}

interface ChatState {
  messagesByConversation: Record<string, Message[]>;
  conversations: Conversation[];
  activeChatId: string | null;
  streamingState: StreamingState;
  isHydrated: boolean;

  hydrate: () => Promise<void>;
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
  setConversations: (conversations: Conversation[]) => void;
  addConversation: (conversation: Conversation) => void;
  updateConversationTitle: (conversationId: string, title: string) => void;
  removeConversation: (conversationId: string) => void;
  updateConversationStarred: (conversationId: string, starred: boolean) => void;
}

export const useChatStore = create<ChatState>((set, _get) => ({
  messagesByConversation: {},
  conversations: [],
  activeChatId: null,
  streamingState: {
    isTyping: false,
    isStreaming: false,
    conversationId: null,
    progress: null,
    progressToolName: null,
  },
  isHydrated: false,

  hydrate: async () => {
    const conversations = await chatDb.getConversations();
    set({ conversations, isHydrated: true });
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

  setConversations: (conversations) => {
    set({ conversations });
    chatDb.saveConversations(conversations);
  },

  addConversation: (conversation) =>
    set((state) => {
      if (state.conversations.some((c) => c.id === conversation.id)) {
        return state;
      }
      const updated = [conversation, ...state.conversations];
      chatDb.saveConversations(updated);
      return { conversations: updated };
    }),

  updateConversationTitle: (conversationId, title) =>
    set((state) => {
      const updated = state.conversations.map((c) =>
        c.id === conversationId ? { ...c, title } : c,
      );
      chatDb.saveConversations(updated);
      return { conversations: updated };
    }),

  removeConversation: (conversationId) =>
    set((state) => {
      const updated = state.conversations.filter(
        (c) => c.id !== conversationId,
      );
      chatDb.saveConversations(updated);
      chatDb.deleteConversation(conversationId);
      return { conversations: updated };
    }),

  updateConversationStarred: (conversationId, starred) =>
    set((state) => {
      const updated = state.conversations.map((c) =>
        c.id === conversationId ? { ...c, is_starred: starred } : c,
      );
      chatDb.saveConversations(updated);
      return { conversations: updated };
    }),
}));
