import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Conversation } from "@/features/chat/types";
import { apiService } from "@/lib/api";
import { chatDb } from "@/lib/db/chatDb";

interface ApiConversation {
  _id: string;
  user_id: string;
  conversation_id: string;
  description: string;
  is_system_generated: boolean;
  system_purpose: string | null;
  is_unread?: boolean;
  is_starred?: boolean;
  createdAt: string;
  updatedAt?: string;
}

interface ConversationsResponse {
  conversations: ApiConversation[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

function normalizeConversation(apiConv: ApiConversation): Conversation {
  return {
    id: apiConv.conversation_id,
    title: apiConv.description || "Untitled conversation",
    created_at: apiConv.createdAt,
    updated_at: apiConv.updatedAt || apiConv.createdAt,
    is_unread: apiConv.is_unread,
    is_starred: apiConv.is_starred,
  };
}

async function fetchConversationsList(): Promise<Conversation[]> {
  const data = await apiService.get<ConversationsResponse>(
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
