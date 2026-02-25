import { useCallback, useRef, useState } from "react";

import { type Conversation, chatApi } from "@/features/chat/api/chatApi";
import { CONVERSATIONS_PAGE_SIZE } from "@/features/chat/constants";
import { db } from "@/lib/db/chatDb";

interface InfiniteConversationsState {
  isLoadingMore: boolean;
  hasMore: boolean;
  currentPage: number;
  totalPages: number;
  error: string | null;
}

export const useInfiniteConversations = () => {
  const [state, setState] = useState<InfiniteConversationsState>({
    isLoadingMore: false,
    hasMore: true,
    currentPage: 1, // Page 1 is loaded by sync service
    totalPages: 1,
    error: null,
  });

  const loadingRef = useRef(false);

  const loadMoreConversations = useCallback(async () => {
    // Prevent concurrent loads
    if (loadingRef.current || !state.hasMore) return;

    loadingRef.current = true;
    setState((prev) => ({ ...prev, isLoadingMore: true, error: null }));

    try {
      const nextPage = state.currentPage + 1;
      const response = await chatApi.fetchConversations(
        nextPage,
        CONVERSATIONS_PAGE_SIZE,
      );

      if (response.conversations.length > 0) {
        // Convert API conversations to IConversation format and store in IndexedDB
        const mappedConversations = response.conversations.map(
          (conv: Conversation) => ({
            id: conv.conversation_id,
            title: conv.description || "Untitled conversation",
            description: conv.description,
            userId: conv.user_id,
            starred: conv.starred ?? false,
            isSystemGenerated: conv.is_system_generated ?? false,
            systemPurpose: conv.system_purpose ?? null,
            isUnread: conv.is_unread ?? false,
            createdAt: new Date(conv.createdAt),
            updatedAt: conv.updatedAt
              ? new Date(conv.updatedAt)
              : new Date(conv.createdAt),
          }),
        );

        // Store in IndexedDB - this will trigger Zustand store updates via dbEventEmitter
        await db.putConversationsBulk(mappedConversations);
      }

      const hasMore = nextPage < response.total_pages;

      setState({
        isLoadingMore: false,
        hasMore,
        currentPage: nextPage,
        totalPages: response.total_pages,
        error: null,
      });
    } catch (error) {
      console.error("[useInfiniteConversations] Failed to load more:", error);
      setState((prev) => ({
        ...prev,
        isLoadingMore: false,
        error: "Failed to load more conversations",
      }));
    } finally {
      loadingRef.current = false;
    }
  }, [state.hasMore, state.currentPage]);

  const resetPagination = useCallback(() => {
    setState({
      isLoadingMore: false,
      hasMore: true,
      currentPage: 1,
      totalPages: 1,
      error: null,
    });
  }, []);

  return {
    loadMoreConversations,
    resetPagination,
    isLoadingMore: state.isLoadingMore,
    hasMore: state.hasMore,
    totalPages: state.totalPages,
    error: state.error,
  };
};
