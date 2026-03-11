import { useQueryClient } from "@tanstack/react-query";
import { chatApi } from "@/features/chat/api/chat-api";
import { chatKeys, useConversationsQuery } from "@/features/chat/api/queries";
import type { Conversation, GroupedConversations } from "@/features/chat/types";
import { useChatStore } from "@/stores/chat-store";

export type { Conversation, GroupedConversations } from "@/features/chat/types";

interface UseConversationsReturn {
  conversations: Conversation[];
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  deleteConversation: (id: string) => Promise<void>;
  renameConversation: (id: string, title: string) => Promise<void>;
  starConversation: (id: string) => Promise<void>;
  unstarConversation: (id: string) => Promise<void>;
}

export function useConversations(): UseConversationsReturn {
  const { data, isLoading, error, refetch } = useConversationsQuery();
  const queryClient = useQueryClient();
  const store = useChatStore.getState();

  const deleteConversation = async (id: string) => {
    await chatApi.deleteConversation(id);
    store.removeConversation(id);
    queryClient.invalidateQueries({ queryKey: chatKeys.conversations() });
  };

  const renameConversation = async (id: string, title: string) => {
    await chatApi.renameConversation(id, title);
    store.updateConversationTitle(id, title);
    queryClient.invalidateQueries({ queryKey: chatKeys.conversations() });
  };

  const starConversation = async (id: string) => {
    await chatApi.toggleStarConversation(id, true);
    store.updateConversationStarred(id, true);
    queryClient.invalidateQueries({ queryKey: chatKeys.conversations() });
  };

  const unstarConversation = async (id: string) => {
    await chatApi.toggleStarConversation(id, false);
    store.updateConversationStarred(id, false);
    queryClient.invalidateQueries({ queryKey: chatKeys.conversations() });
  };

  return {
    conversations: data ?? [],
    isLoading,
    error: error?.message ?? null,
    refetch: async () => {
      await refetch();
    },
    deleteConversation,
    renameConversation,
    starConversation,
    unstarConversation,
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

  conversations.forEach((conv) => {
    const convDate = new Date(conv.created_at);

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
  });

  return {
    starred,
    today: todayChats,
    yesterday: yesterdayChats,
    lastWeek: lastWeekChats,
    last30Days: last30DaysChats,
    older: olderChats,
  };
}
