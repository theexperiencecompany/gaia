import { useEffect } from "react";
import { create } from "zustand";

import type { IConversation, IMessage } from "@/lib/db/chatDb";
import { db, dbEventEmitter } from "@/lib/db/chatDb";
import type { FileData } from "@/types/shared";

type LoadingStatus = "idle" | "loading" | "success" | "error";

// Optimistic message for new conversations (before conversation ID is assigned)
// These are stored in Zustand only to avoid IndexedDB pollution if not cleared properly
interface OptimisticMessage {
  id: string; // Temporary optimistic ID
  conversationId: string | null; // null for new conversations, set for existing ones
  content: string;
  role: "user" | "assistant";
  createdAt: Date;
  fileIds?: string[];
  fileData?: FileData[];
  toolName?: string | null;
  toolCategory?: string | null;
  workflowId?: string | null;
  metadata?: Record<string, unknown>;
}

interface ChatState {
  conversations: IConversation[];
  messagesByConversation: Record<string, IMessage[]>;
  activeConversationId: string | null;
  conversationsLoadingStatus: LoadingStatus;
  // Single optimistic message for new conversations (not yet persisted to IndexedDB)
  // Only ONE optimistic message can exist at a time - enforced by using single object instead of array
  optimisticMessage: OptimisticMessage | null;
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
  removeMessage: (messageId: string, conversationId: string) => void;
  setActiveConversationId: (id: string | null) => void;
  setConversationsLoadingStatus: (status: LoadingStatus) => void;
  // Optimistic message management for new conversations (single message only)
  setOptimisticMessage: (message: OptimisticMessage | null) => void;
  clearOptimisticMessage: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  conversations: [],
  messagesByConversation: {},
  activeConversationId: null,
  conversationsLoadingStatus: "idle",
  // Single optimistic message for new conversations (prevents IndexedDB pollution)
  // Only one message at a time - enforced by type
  optimisticMessage: null,

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

  removeMessage: (messageId, conversationId) =>
    set((state) => {
      const messages = state.messagesByConversation[conversationId] ?? [];
      const filteredMessages = messages.filter((msg) => msg.id !== messageId);

      return {
        messagesByConversation: {
          ...state.messagesByConversation,
          [conversationId]: filteredMessages,
        },
      };
    }),

  setActiveConversationId: (id) => set({ activeConversationId: id }),

  setConversationsLoadingStatus: (status) =>
    set({ conversationsLoadingStatus: status }),

  // Set the single optimistic message (replaces any existing one)
  // Only one optimistic message can exist at a time
  setOptimisticMessage: (message) => set({ optimisticMessage: message }),

  // Clear the optimistic message (set to null)
  clearOptimisticMessage: () => set({ optimisticMessage: null }),
}));

// Event-driven synchronization with IndexedDB
let syncInitialized = false; // Guard against multiple initializations

export const useChatStoreSync = () => {
  useEffect(() => {
    // Prevent multiple sync initializations
    if (syncInitialized) {
      console.warn("[chatStore] Sync already initialized, skipping");
      return;
    }
    syncInitialized = true;

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
            useChatStore
              .getState()
              .setMessagesForConversation(conversationId, messages);
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

    const handleMessageDeleted = (
      messageId: string,
      conversationId: string,
    ) => {
      useChatStore.getState().removeMessage(messageId, conversationId);
    };

    const handleMessagesSynced = (
      conversationId: string,
      messages: IMessage[],
    ) => {
      useChatStore
        .getState()
        .setMessagesForConversation(conversationId, messages);
    };

    const handleMessageIdReplaced = (oldId: string, newMessage: IMessage) => {
      const state = useChatStore.getState();
      const messages =
        state.messagesByConversation[newMessage.conversationId] ?? [];
      const updatedMessages = messages.map((msg) =>
        msg.id === oldId ? newMessage : msg,
      );
      state.setMessagesForConversation(
        newMessage.conversationId,
        updatedMessages,
      );
    };

    const handleConversationAdded = (conversation: IConversation) => {
      useChatStore.getState().upsertConversation(conversation);
    };

    const handleConversationUpdated = (conversation: IConversation) => {
      useChatStore.getState().upsertConversation(conversation);
    };

    const handleConversationDeleted = (conversationId: string) => {
      useChatStore.getState().removeConversation(conversationId);
    };

    const handleConversationsDeletedBulk = (conversationIds: string[]) => {
      conversationIds.forEach((id) => {
        useChatStore.getState().removeConversation(id);
      });
    };

    dbEventEmitter.on("messageAdded", handleMessageAdded);
    dbEventEmitter.on("messageUpdated", handleMessageUpdated);
    dbEventEmitter.on("messageDeleted", handleMessageDeleted);
    dbEventEmitter.on("messagesSynced", handleMessagesSynced);
    dbEventEmitter.on("messageIdReplaced", handleMessageIdReplaced);
    dbEventEmitter.on("conversationAdded", handleConversationAdded);
    dbEventEmitter.on("conversationUpdated", handleConversationUpdated);
    dbEventEmitter.on("conversationDeleted", handleConversationDeleted);
    dbEventEmitter.on(
      "conversationsDeletedBulk",
      handleConversationsDeletedBulk,
    );

    return () => {
      isActive = false;
      syncInitialized = false; // Reset flag on cleanup
      dbEventEmitter.off("messageAdded", handleMessageAdded);
      dbEventEmitter.off("messageUpdated", handleMessageUpdated);
      dbEventEmitter.off("messageDeleted", handleMessageDeleted);
      dbEventEmitter.off("messagesSynced", handleMessagesSynced);
      dbEventEmitter.off("messageIdReplaced", handleMessageIdReplaced);
      dbEventEmitter.off("conversationAdded", handleConversationAdded);
      dbEventEmitter.off("conversationUpdated", handleConversationUpdated);
      dbEventEmitter.off("conversationDeleted", handleConversationDeleted);
      dbEventEmitter.off(
        "conversationsDeletedBulk",
        handleConversationsDeletedBulk,
      );
    };
  }, []);
};
