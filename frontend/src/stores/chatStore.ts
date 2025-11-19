import { create } from "zustand";
import { useEffect } from "react";

import type { IConversation, IMessage } from "@/lib/db/chatDb";
import { db, dbEventEmitter } from "@/lib/db/chatDb";

type LoadingStatus = "idle" | "loading" | "success" | "error";

interface ChatState {
  conversations: IConversation[];
  messagesByConversation: Record<string, IMessage[]>;
  activeConversationId: string | null;
  conversationsLoadingStatus: LoadingStatus;
  setConversations: (conversations: IConversation[]) => void;
  upsertConversation: (conversation: IConversation) => void;
  updateConversation: (
    conversationId: string,
    updates: Partial<IConversation>,
  ) => void;
  setMessagesForConversation: (
    conversationId: string,
    messages: IMessage[],
  ) => void;
  addOrUpdateMessage: (message: IMessage) => void;
  removeConversation: (conversationId: string) => void;
  setActiveConversationId: (id: string | null) => void;
  setConversationsLoadingStatus: (status: LoadingStatus) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  conversations: [],
  messagesByConversation: {},
  activeConversationId: null,
  conversationsLoadingStatus: "idle",

  setConversations: (conversations) =>
    set({ conversations: [...conversations] }),

  upsertConversation: (conversation) =>
    set((state) => {
      const index = state.conversations.findIndex(
        (existing) => existing.id === conversation.id,
      );

      const conversations =
        index === -1
          ? [...state.conversations, conversation]
          : state.conversations.map((existing) =>
              existing.id === conversation.id ? conversation : existing,
            );

      return { conversations };
    }),

  updateConversation: (conversationId, updates) =>
    set((state) => ({
      conversations: state.conversations.map((conv) =>
        conv.id === conversationId ? { ...conv, ...updates } : conv,
      ),
    })),

  setMessagesForConversation: (conversationId, messages) =>
    set((state) => ({
      messagesByConversation: {
        ...state.messagesByConversation,
        [conversationId]: [...messages],
      },
    })),

  addOrUpdateMessage: (message) =>
    set((state) => {
      const { conversationId } = message;
      const existingMessages =
        state.messagesByConversation[conversationId] ?? [];
      const index = existingMessages.findIndex(
        (existing) => existing.id === message.id,
      );

      const updatedMessages =
        index === -1
          ? [...existingMessages, message]
          : existingMessages.map((existing) =>
              existing.id === message.id ? message : existing,
            );

      return {
        messagesByConversation: {
          ...state.messagesByConversation,
          [conversationId]: updatedMessages,
        },
      };
    }),

  removeConversation: (conversationId) =>
    set((state) => {
      const conversations = state.conversations.filter(
        (conversation) => conversation.id !== conversationId,
      );

      const { [conversationId]: _removed, ...remainingMessages } =
        state.messagesByConversation;

      const activeConversationId =
        state.activeConversationId === conversationId
          ? null
          : state.activeConversationId;

      return {
        conversations,
        messagesByConversation: remainingMessages,
        activeConversationId,
      };
    }),

  setActiveConversationId: (id) => set({ activeConversationId: id }),

  setConversationsLoadingStatus: (status) =>
    set({ conversationsLoadingStatus: status }),
}));

// Event-driven synchronization with IndexedDB
export const useChatStoreSync = () => {
  useEffect(() => {
    let isActive = true;

    // Initial hydration from IndexedDB
    const hydrateFromIndexedDB = async () => {
      try {
        // Load all conversations
        const conversations = await db.getAllConversations();
        if (isActive) {
          useChatStore.getState().setConversations(conversations);
        }

        // Load messages for all conversations
        const conversationIds = await db.getConversationIdsWithMessages();
        for (const conversationId of conversationIds) {
          if (!isActive) break;
          const messages = await db.getMessagesForConversation(conversationId);
          if (isActive && messages.length > 0) {
            useChatStore.getState().setMessagesForConversation(conversationId, messages);
          }
        }
      } catch (error) {
        console.error("Failed to hydrate from IndexedDB:", error);
      }
    };

    hydrateFromIndexedDB();

    // Event handlers
    const handleMessageAdded = (message: IMessage) => {
      useChatStore.getState().addOrUpdateMessage(message);
    };

    const handleMessageUpdated = (message: IMessage) => {
      useChatStore.getState().addOrUpdateMessage(message);
    };

    const handleMessagesSynced = (
      conversationId: string,
      messages: IMessage[],
    ) => {
      useChatStore
        .getState()
        .setMessagesForConversation(conversationId, messages);
    };

    const handleConversationAdded = (conversation: IConversation) => {
      useChatStore.getState().upsertConversation(conversation);
    };

    const handleConversationUpdated = (conversation: IConversation) => {
      useChatStore.getState().upsertConversation(conversation);
    };

    dbEventEmitter.on("messageAdded", handleMessageAdded);
    dbEventEmitter.on("messageUpdated", handleMessageUpdated);
    dbEventEmitter.on("messagesSynced", handleMessagesSynced);
    dbEventEmitter.on("conversationAdded", handleConversationAdded);
    dbEventEmitter.on("conversationUpdated", handleConversationUpdated);

    return () => {
      isActive = false;
      dbEventEmitter.off("messageAdded", handleMessageAdded);
      dbEventEmitter.off("messageUpdated", handleMessageUpdated);
      dbEventEmitter.off("messagesSynced", handleMessagesSynced);
      dbEventEmitter.off("conversationAdded", handleConversationAdded);
      dbEventEmitter.off("conversationUpdated", handleConversationUpdated);
    };
  }, []);
};
