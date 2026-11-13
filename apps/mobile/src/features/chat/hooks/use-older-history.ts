import { createOlderHistoryLoader, oldestSeq } from "@gaia/shared/conversation";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { chatDb } from "@/lib/db/chatDb";
import { chatApi, type Message } from "../api/chat-api";
import { chatKeys } from "../api/queries";

/** The list's start-reached handler: prepend the page before the oldest cached message. */
export function useOlderHistory(conversationId: string | null): () => void {
  const queryClient = useQueryClient();

  const loadOlder = useMemo(() => {
    if (!conversationId) return null;
    const messagesKey = chatKeys.messages(conversationId);
    return createOlderHistoryLoader<Message>({
      hasOlder: () =>
        queryClient.getQueryData<boolean>(chatKeys.hasOlder(conversationId)) ??
        false,
      oldestLoadedSeq: () =>
        oldestSeq(queryClient.getQueryData<Message[]>(messagesKey) ?? []),
      fetchPage: (beforeSeq, limit) =>
        chatApi.fetchMessagesBefore(conversationId, beforeSeq, limit),
      applyPage: (page) => {
        const next = [
          ...page.messages,
          ...(queryClient.getQueryData<Message[]>(messagesKey) ?? []),
        ];
        queryClient.setQueryData(messagesKey, next);
        queryClient.setQueryData(
          chatKeys.hasOlder(conversationId),
          page.has_more,
        );
        chatDb.saveMessages(conversationId, next).catch((err: unknown) => {
          console.warn("[use-older-history] Failed to persist messages:", err);
        });
      },
    });
  }, [conversationId, queryClient]);

  return useCallback(() => {
    loadOlder?.().catch((error: unknown) => {
      console.error(
        "[use-older-history] Failed to load older messages:",
        error,
      );
    });
  }, [loadOlder]);
}
