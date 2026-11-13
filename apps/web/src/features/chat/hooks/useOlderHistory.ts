import { createOlderHistoryLoader, oldestSeq } from "@shared/conversation";
import { useEffect, useMemo } from "react";
import { useMessageScrollerScrollable } from "@/components/ui/message-scroller";
import { chatApi } from "@/features/chat/api/chatApi";
import { applyOlderMessagesPage } from "@/services/syncService";
import { useChatStore } from "@/stores/chatStore";

/** Load the previous page of the active conversation whenever the reader reaches the top. */
export const useOlderHistory = (): void => {
  const conversationId = useChatStore((state) => state.activeConversationId);
  const hasOlder = useChatStore(
    (state) =>
      state.conversations.find((conv) => conv.id === conversationId)
        ?.hasOlder ?? false,
  );
  const messageCount = useChatStore((state) =>
    conversationId
      ? (state.messagesByConversation[conversationId]?.length ?? 0)
      : 0,
  );
  const { start: canScrollUp } = useMessageScrollerScrollable();

  const loadOlder = useMemo(() => {
    if (!conversationId) return null;
    return createOlderHistoryLoader({
      hasOlder: () =>
        useChatStore
          .getState()
          .conversations.find((conv) => conv.id === conversationId)?.hasOlder ??
        false,
      oldestLoadedSeq: () =>
        oldestSeq(
          useChatStore.getState().messagesByConversation[conversationId] ?? [],
        ),
      fetchPage: (beforeSeq, limit) =>
        chatApi.fetchMessagesBefore(conversationId, beforeSeq, limit),
      applyPage: (page) => applyOlderMessagesPage(conversationId, page),
    });
  }, [conversationId]);

  useEffect(() => {
    if (!loadOlder || !hasOlder || canScrollUp || messageCount === 0) return;
    loadOlder().catch((error: unknown) => {
      console.error("[useOlderHistory] Failed to load older messages:", error);
    });
  }, [loadOlder, hasOlder, canScrollUp, messageCount]);
};
