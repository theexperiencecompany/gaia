import { useEffect } from "react";
import { create } from "zustand";
import type { IConversation } from "@/lib/db/chatDb";
import { db, dbEventEmitter } from "@/lib/db/chatDb";
import type {
  ReplyToMessageData,
  SelectedCalendarEventData,
} from "@/stores/composerStore.types";
import type { ArtifactData } from "@/types/features/toolDataTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared/fileTypes";

// Optimistic message for new conversations (before conversation ID is assigned)
// These are stored in Zustand only to avoid IndexedDB pollution if not cleared properly
export interface OptimisticMessage {
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
  selectedWorkflow?: WorkflowData | null;
  selectedCalendarEvent?: SelectedCalendarEventData | null;
  replyToMessage?: ReplyToMessageData | null;
  metadata?: Record<string, unknown>;
  // The send never reached the backend. For a new conversation this bubble is
  // the only record of the message, so it is marked rather than cleared.
  failed?: boolean;
}

interface ChatState {
  conversations: IConversation[];
  // Per-conversation artifact registry keyed by path, resolving a message's path references to
  // full ArtifactData. Hydrated from IConversation.artifacts on load/sync, updated live by SSE,
  // and persisted back to IndexedDB at end-of-stream.
  artifactsByConversation: Record<string, Record<string, ArtifactData>>;
  activeConversationId: string | null;
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
  removeConversation: (conversationId: string) => void;
  setConversationArtifacts: (
    conversationId: string,
    artifacts: ArtifactData[],
  ) => void;
  setActiveConversationId: (id: string | null) => void;
  setHydrationCompleted: (completed: boolean) => void;
  // Optimistic message management for new conversations (single message only)
  setOptimisticMessage: (message: OptimisticMessage | null) => void;
  clearOptimisticMessage: () => void;
  /** Flag the optimistic message as undelivered, keeping it on screen. */
  markOptimisticMessageFailed: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  conversations: [],
  artifactsByConversation: {},
  activeConversationId: null,
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

  removeConversation: (conversationId) =>
    set((state) => {
      const conversations = state.conversations.filter(
        (conversation) => conversation.id !== conversationId,
      );

      const activeConversationId =
        state.activeConversationId === conversationId
          ? null
          : state.activeConversationId;

      return { conversations, activeConversationId };
    }),

  // Server registry entries persist only per-file fields (path, size, mtime, content type) —
  // the conversation id is the document key, not an element field. Stamp it back on as
  // session_id so every map entry is complete ArtifactData (fetch URLs are built from it).
  setConversationArtifacts: (conversationId, artifacts) =>
    set((state) => {
      const registry: Record<string, ArtifactData> = {};
      for (const artifact of artifacts) {
        if (!artifact?.path) continue;
        registry[artifact.path] = { ...artifact, session_id: conversationId };
      }
      return {
        artifactsByConversation: {
          ...state.artifactsByConversation,
          [conversationId]: registry,
        },
      };
    }),

  setActiveConversationId: (id) => set({ activeConversationId: id }),

  setHydrationCompleted: (completed) => set({ hydrationCompleted: completed }),

  // Set the single optimistic message (replaces any existing one)
  // Only one optimistic message can exist at a time
  setOptimisticMessage: (message) => set({ optimisticMessage: message }),

  // Clear the optimistic message (set to null)
  clearOptimisticMessage: () => set({ optimisticMessage: null }),

  markOptimisticMessageFailed: () =>
    set((state) => ({
      optimisticMessage: state.optimisticMessage
        ? { ...state.optimisticMessage, failed: true }
        : null,
    })),
}));

// Hydrate immediately on module load (before any React renders)
// This runs once when the module is first imported, AFTER the store is defined
let hydrationStarted = false;
const startHydration = async () => {
  if (hydrationStarted) return;
  hydrationStarted = true;

  try {
    const conversations = await db.getAllConversations();

    useChatStore.getState().setConversations(conversations);

    // Seed the artifact lookup map from each conversation's persisted registry.
    for (const conversation of conversations) {
      if (conversation.artifacts?.length) {
        useChatStore
          .getState()
          .setConversationArtifacts(conversation.id, conversation.artifacts);
      }
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

// Stable empty reference so conversations with no artifacts don't trigger
// re-renders by returning a fresh object each call.
const EMPTY_ARTIFACT_MAP: Record<string, ArtifactData> = {};

/** Path→ArtifactData map for a conversation, for resolving message references. */
export const useConversationArtifacts = (conversationId: string) =>
  useChatStore(
    (state) =>
      state.artifactsByConversation[conversationId] ?? EMPTY_ARTIFACT_MAP,
  );

// Event-driven synchronization with IndexedDB
// Hydration happens at module load (above), this just sets up event listeners
export const useChatStoreSync = () => {
  useEffect(() => {
    // Event handlers for real-time updates from IndexedDB

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

    dbEventEmitter.on("conversationAdded", handleConversationAdded);
    dbEventEmitter.on("conversationUpdated", handleConversationUpdated);
    dbEventEmitter.on("conversationDeleted", handleConversationDeleted);
    dbEventEmitter.on(
      "conversationsDeletedBulk",
      handleConversationsDeletedBulk,
    );

    return () => {
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
