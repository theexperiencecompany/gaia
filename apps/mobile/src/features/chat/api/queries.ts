import type {
  ConversationListResponse,
  ConversationSummary,
} from "@gaia/shared/api/generated";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Conversation } from "@/features/chat/types";
import { apiService } from "@/lib/api";
import { chatDb } from "@/lib/db/chatDb";

const EPOCH_ISO = new Date(0).toISOString();

function normalizeConversation(apiConv: ConversationSummary): Conversation {
  return {
    id: apiConv.conversation_id,
    title: apiConv.description || "Untitled conversation",
    // An undated row sorts as the epoch, as the web list does.
    created_at: apiConv.createdAt ?? EPOCH_ISO,
    updated_at: apiConv.updatedAt ?? apiConv.createdAt ?? EPOCH_ISO,
    is_unread: apiConv.is_unread ?? undefined,
    is_starred: apiConv.starred ?? undefined,
  };
}

async function fetchConversationsList(): Promise<Conversation[]> {
  const data = await apiService.get<ConversationListResponse>(
    "/conversations?page=1&limit=100",
  );
  const conversations = (data.conversations || []).map(normalizeConversation);
  // Persist so the next launch can render the list instantly from
  // AsyncStorage while a fresh fetch runs in the background.
  chatDb.saveConversations(conversations).catch((err) => {
    console.warn("[queries] Failed to persist conversations:", err);
  });
  return conversations;
}

export const chatKeys = {
  all: ["chat"] as const,
  conversations: () => [...chatKeys.all, "conversations"] as const,
  conversation: (id: string) => [...chatKeys.all, "conversation", id] as const,
  /** The newest page of a conversation's log, folded into its live view. */
  page: (id: string) => [...chatKeys.all, "page", id] as const,
};

export function useConversationsQuery() {
  return useQuery({
    queryKey: chatKeys.conversations(),
    queryFn: fetchConversationsList,
    staleTime: 15_000,
  });
}

export function useChatQueryClient() {
  const queryClient = useQueryClient();

  const invalidateConversations = () => {
    queryClient.invalidateQueries({ queryKey: chatKeys.conversations() });
  };

  const updateConversationInCache = (
    conversationId: string,
    updates: Partial<Conversation>,
  ) => {
    queryClient.setQueryData<Conversation[]>(
      chatKeys.conversations(),
      (prev) => {
        if (!prev) return prev;
        const next = prev.map((c) =>
          c.id === conversationId ? { ...c, ...updates } : c,
        );
        // Keep the AsyncStorage seed in sync so the next launch matches.
        chatDb.saveConversations(next).catch((err) => {
          console.warn("[queries] Failed to persist conversations:", err);
        });
        return next;
      },
    );
  };

  /** Optimistically drop a conversation from the list (and local seed). */
  const removeConversationFromCache = (conversationId: string) => {
    queryClient.setQueryData<Conversation[]>(
      chatKeys.conversations(),
      (prev) => {
        if (!prev) return prev;
        const next = prev.filter((c) => c.id !== conversationId);
        chatDb.saveConversations(next).catch((err) => {
          console.warn("[queries] Failed to persist conversations:", err);
        });
        chatDb.deleteConversation(conversationId).catch(() => undefined);
        return next;
      },
    );
  };

  return {
    invalidateConversations,
    updateConversationInCache,
    removeConversationFromCache,
  };
}
