import { createOlderHistoryLoader } from "@shared/conversation";
import { useEffect, useMemo } from "react";
import { useMessageScrollerScrollable } from "@/components/ui/message-scroller";
import { chatApi } from "@/features/chat/api/chatApi";
import { applyConversationPage } from "@/features/chat/live/connection";
import {
  liveConversation,
  useLiveConversation,
} from "@/features/chat/live/liveConversationStore";
import { useChatStore } from "@/stores/chatStore";

/** Load the previous page of the active conversation's log whenever the reader reaches the top. */
export const useOlderHistory = (): void => {
  const conversationId = useChatStore((state) => state.activeConversationId);
  const { view, olderBefore } = useLiveConversation(conversationId);
  const { start: canScrollUp } = useMessageScrollerScrollable();

  const loadOlder = useMemo(() => {
    if (!conversationId) return null;
    return createOlderHistoryLoader({
      olderBefore: () => liveConversation(conversationId).olderBefore,
      fetchPage: (beforeSeq, limit) =>
        chatApi.fetchEntriesBefore(conversationId, beforeSeq, limit),
      applyPage: (page) => applyConversationPage(conversationId, page),
    });
  }, [conversationId]);

  const held = view.entries.length;
  useEffect(() => {
    if (!loadOlder || olderBefore === null || canScrollUp || held === 0) return;
    loadOlder().catch((error: unknown) => {
      console.error("[useOlderHistory] Failed to load older entries:", error);
    });
  }, [loadOlder, olderBefore, canScrollUp, held]);
};
