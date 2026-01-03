import { useCallback, useEffect, useState } from "react";
import type { Conversation } from "@/features/chat/types";
import { apiService } from "@/lib/api";

// Re-export for backwards compatibility
export type { Conversation, GroupedConversations } from "@/features/chat/types";

// ============================================================================
// API Types (internal to this module)
// ============================================================================

interface ApiConversation {
  _id: string;
  user_id: string;
  conversation_id: string;
  description: string;
  is_system_generated: boolean;
  system_purpose: string | null;
  is_unread?: boolean;
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

// ============================================================================
// Helpers
// ============================================================================

interface UseConversationsReturn {
  conversations: Conversation[];
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

function normalizeConversation(apiConv: ApiConversation): Conversation {
  return {
    id: apiConv.conversation_id,
    title: apiConv.description || "Untitled conversation",
    created_at: apiConv.createdAt,
    updated_at: apiConv.updatedAt || apiConv.createdAt,
    is_unread: apiConv.is_unread,
  };
}

export function useConversations(): UseConversationsReturn {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchConversations = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);

      const data = await apiService.get<ConversationsResponse>(
        "/conversations?page=1&limit=100",
      );

      const normalizedConversations = (data.conversations || []).map(
        normalizeConversation,
      );
      setConversations(normalizedConversations);
    } catch (err) {
      console.error("Error fetching conversations:", err);
      setError(
        err instanceof Error ? err.message : "Failed to fetch conversations",
      );
      setConversations([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  return {
    conversations,
    isLoading,
    error,
    refetch: fetchConversations,
  };
}

export function groupConversationsByDate(conversations: Conversation[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const lastWeek = new Date(today);
  lastWeek.setDate(lastWeek.getDate() - 7);

  const starred: Conversation[] = [];
  const todayChats: Conversation[] = [];
  const yesterdayChats: Conversation[] = [];
  const lastWeekChats: Conversation[] = [];
  const olderChats: Conversation[] = [];

  conversations.forEach((conv) => {
    const convDate = new Date(conv.updated_at || conv.created_at);

    if (conv.is_starred) {
      starred.push(conv);
    } else if (convDate >= today) {
      todayChats.push(conv);
    } else if (convDate >= yesterday) {
      yesterdayChats.push(conv);
    } else if (convDate >= lastWeek) {
      lastWeekChats.push(conv);
    } else {
      olderChats.push(conv);
    }
  });

  return {
    starred,
    today: todayChats,
    yesterday: yesterdayChats,
    lastWeek: lastWeekChats,
    older: olderChats,
  };
}
