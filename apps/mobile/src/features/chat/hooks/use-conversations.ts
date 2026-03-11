import { useConversationsQuery } from "@/features/chat/api/queries";
import type { Conversation, GroupedConversations } from "@/features/chat/types";

export type { Conversation, GroupedConversations } from "@/features/chat/types";

interface UseConversationsReturn {
  conversations: Conversation[];
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export function useConversations(): UseConversationsReturn {
  const { data, isLoading, error, refetch } = useConversationsQuery();

  return {
    conversations: data ?? [],
    isLoading,
    error: error?.message ?? null,
    refetch: async () => {
      await refetch();
    },
  };
}

export function groupConversationsByDate(
  conversations: Conversation[],
): GroupedConversations {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const lastWeek = new Date(today);
  lastWeek.setDate(lastWeek.getDate() - 7);
  const last30Days = new Date(today);
  last30Days.setDate(last30Days.getDate() - 30);

  const starred: Conversation[] = [];
  const todayChats: Conversation[] = [];
  const yesterdayChats: Conversation[] = [];
  const lastWeekChats: Conversation[] = [];
  const last30DaysChats: Conversation[] = [];
  const olderChats: Conversation[] = [];

  for (const conv of conversations) {
    const convDate = new Date(conv.updated_at || conv.created_at);

    if (conv.is_starred) {
      starred.push(conv);
    } else if (convDate >= today) {
      todayChats.push(conv);
    } else if (convDate >= yesterday) {
      yesterdayChats.push(conv);
    } else if (convDate >= lastWeek) {
      lastWeekChats.push(conv);
    } else if (convDate >= last30Days) {
      last30DaysChats.push(conv);
    } else {
      olderChats.push(conv);
    }
  }

  return {
    starred,
    today: todayChats,
    yesterday: yesterdayChats,
    lastWeek: lastWeekChats,
    last30Days: last30DaysChats,
    older: olderChats,
  };
}
