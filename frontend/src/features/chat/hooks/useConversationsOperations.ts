import { useCallback } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import { batchSyncConversations } from "@/services/syncService";
import { useChatStore } from "@/stores/chatStore";

export const useConversationsOperations = () => {
  const setConversationsLoadingStatus = useChatStore(
    (state) => state.setConversationsLoadingStatus,
  );

  const fetchConversations = useCallback(
    async (page = 1, limit = 20, append = true) => {
      setConversationsLoadingStatus("loading");

      try {
        await batchSyncConversations();

        const data = await chatApi.fetchConversations(page, limit);

        const paginationMeta = {
          total: data.total ?? 0,
          page: data.page ?? 1,
          limit: data.limit ?? limit,
          total_pages: data.total_pages ?? 1,
        };

        setConversationsLoadingStatus("success");

        return { conversations: data.conversations, paginationMeta };
      } catch (error) {
        setConversationsLoadingStatus("error");
        throw error;
      }
    },
    [setConversationsLoadingStatus],
  );

  return {
    fetchConversations,
  };
};
