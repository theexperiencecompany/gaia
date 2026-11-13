import { createOlderHistoryLoader } from "@gaia/shared/conversation";
import { useCallback, useMemo } from "react";
import { chatApi } from "../api/chat-api";
import { applyConversationPage } from "../live/connection";
import { liveConversation } from "../live/live-conversation-store";

/** The list's start-reached handler: prepend the page of the log before the oldest held entry. */
export function useOlderHistory(conversationId: string | null): () => void {
  const loadOlder = useMemo(() => {
    if (!conversationId) return null;
    return createOlderHistoryLoader({
      olderBefore: () => liveConversation(conversationId).olderBefore,
      fetchPage: (beforeSeq, limit) =>
        chatApi.fetchEntriesBefore(conversationId, beforeSeq, limit),
      applyPage: (page) => applyConversationPage(conversationId, page),
    });
  }, [conversationId]);

  return useCallback(() => {
    loadOlder?.().catch((error: unknown) => {
      console.error(
        "[use-older-history] Failed to load older messages:",
        error,
      );
    });
  }, [loadOlder]);
}
