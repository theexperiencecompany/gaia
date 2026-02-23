import { useEffect } from "react";
import { create } from "zustand";

import type { IConversation, IMessage } from "@/lib/db/chatDb";
import { db, dbEventEmitter } from "@/lib/db/chatDb";
import type { FileData } from "@/types/shared";

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
  streamingConversationId: string | null; // ID of conversation currently streaming
  hydrationCompleted: boolean; // True when IndexedDB hydration is done
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
  setStreamingConversationId: (id: string | null) => void;
  setHydrationCompleted: (completed: boolean) => void;
  // Optimistic message management for new conversations (single message only)
  setOptimisticMessage: (message: OptimisticMessage | null) => void;
  clearOptimisticMessage: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  conversations: [],
  messagesByConversation: {},
  activeConversationId: null,
  streamingConversationId: null, // Track which conversation is streaming
  hydrationCompleted: false, // Becomes true when IndexedDB hydration is done
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

      let updatedMessages =
        index === -1
          ? [...existingMessages, message]
          : existingMessages.map((existing) =>
              existing.id === message.id ? message : existing,
            );

      // Sort by createdAt to ensure correct chronological order
      // This is critical: events may arrive out of order (bot before user)
      updatedMessages = updatedMessages.sort(
        (a, b) => a.createdAt.getTime() - b.createdAt.getTime(),
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

      // Clear streaming indicator if the removed conversation was being streamed
      const streamingConversationId =
        state.streamingConversationId === conversationId
          ? null
          : state.streamingConversationId;

      return {
        conversations,
        messagesByConversation: remainingMessages,
        activeConversationId,
        streamingConversationId,
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

  setStreamingConversationId: (id) => set({ streamingConversationId: id }),

  setHydrationCompleted: (completed) => set({ hydrationCompleted: completed }),

  // Set the single optimistic message (replaces any existing one)
  // Only one optimistic message can exist at a time
  setOptimisticMessage: (message) => set({ optimisticMessage: message }),

  // Clear the optimistic message (set to null)
  clearOptimisticMessage: () => set({ optimisticMessage: null }),
}));

// Hydrate immediately on module load (before any React renders)
// This runs once when the module is first imported, AFTER the store is defined
let hydrationStarted = false;
const startHydration = async () => {
  if (hydrationStarted) return;
  hydrationStarted = true;

  try {
    // Load all conversations and messages in parallel (2 queries total)
    const [conversations, allMessages] = await Promise.all([
      db.getAllConversations(),
      db.getAllMessages(),
    ]);

    useChatStore.getState().setConversations(conversations);

    // Group messages by conversationId client-side (instant, no I/O)
    const messagesByConversation = allMessages.reduce(
      (acc, msg) => {
        if (!acc[msg.conversationId]) acc[msg.conversationId] = [];
        acc[msg.conversationId].push(msg);
        return acc;
      },
      {} as Record<string, IMessage[]>,
    );

    // Set all messages at once
    for (const [conversationId, messages] of Object.entries(
      messagesByConversation,
    )) {
      useChatStore
        .getState()
        .setMessagesForConversation(conversationId, messages);
    }
  } catch (error) {
    console.error("Failed to hydrate from IndexedDB:", error);
  } finally {
    useChatStore.getState().setHydrationCompleted(true);
  }
};

// Start hydration immediately (client-side only)
if (typeof window !== "undefined") {
  startHydration();
}

// Event-driven synchronization with IndexedDB
// Hydration happens at module load (above), this just sets up event listeners
export const useChatStoreSync = () => {
  useEffect(() => {
    // Event handlers for real-time updates from IndexedDB

    const handleMessageUpserted = (message: IMessage) => {
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

      // Check if the old message exists in the store
      const oldIndex = messages.findIndex((msg) => msg.id === oldId);

      let updatedMessages: IMessage[];
      if (oldIndex !== -1) {
        // Replace the old message with the new one
        updatedMessages = messages.map((msg) =>
          msg.id === oldId ? newMessage : msg,
        );
      } else {
        // Old message not found - check if new message already exists (avoid duplicates)
        const newIndex = messages.findIndex((msg) => msg.id === newMessage.id);
        if (newIndex !== -1) {
          // Update existing message with new ID
          updatedMessages = messages.map((msg) =>
            msg.id === newMessage.id ? newMessage : msg,
          );
        } else {
          // Neither found - add the new message
          updatedMessages = [...messages, newMessage];
        }
      }

      // Sort by createdAt to ensure correct order
      updatedMessages.sort(
        (a, b) => a.createdAt.getTime() - b.createdAt.getTime(),
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

    dbEventEmitter.on("messageUpserted", handleMessageUpserted);
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
      dbEventEmitter.off("messageUpserted", handleMessageUpserted);
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
