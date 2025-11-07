import { useCallback } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import { batchSyncConversations } from "@/services/syncService";
import {
  ConversationPaginationMeta,
  useConversationsStore,
} from "@/stores/conversationsStore";

export const useConversationsOperations = () => {
  const {
    setConversations,
    setPaginationMeta,
    setLoading,
    setError,
    clearError,
  } = useConversationsStore();

  const fetchConversations = useCallback(
    async (page = 1, limit = 20, append = true) => {
      setLoading(true);
      clearError();

      try {
        // Trigger batch sync in background
        batchSyncConversations().catch(() => {
          // Ignore sync errors
        });

        const data = await chatApi.fetchConversations(page, limit);

        const conversations = data.conversations ?? [];
        const paginationMeta: ConversationPaginationMeta = {
          total: data.total ?? 0,
          page: data.page ?? 1,
          limit: data.limit ?? limit,
          total_pages: data.total_pages ?? 1,
        };

        setConversations(conversations, append);
        setPaginationMeta(paginationMeta);

        return { conversations, paginationMeta };
      } catch (error) {
        const errorMessage =
          error instanceof Error
            ? error.message
            : "Failed to fetch conversations";
        setError(errorMessage);
        throw error;
      } finally {
        setLoading(false);
      }
    },
    [setConversations, setPaginationMeta, setLoading, setError, clearError],
  );

  return {
    fetchConversations,
  };
};
