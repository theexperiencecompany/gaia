import { createOlderHistoryLoader } from "@gaia/shared/conversation";
import { useRef } from "react";
import { chatApi } from "../api/chat-api";
import { applyConversationPage } from "../live/connection";
import { liveConversation } from "../live/live-conversation-store";

interface OlderHistoryLoader {
  conversationId: string;
  load: () => Promise<void>;
}

/** The list's start-reached handler: prepend the page of the log before the oldest held entry. */
export function useOlderHistory(conversationId: string | null): () => void {
  // One loader per conversation, so a second start-reached joins the page already in flight.
  const loader = useRef<OlderHistoryLoader | null>(null);

  return () => {
    if (!conversationId) return;
    if (loader.current?.conversationId !== conversationId) {
      loader.current = {
        conversationId,
        load: createOlderHistoryLoader({
          olderBefore: () => liveConversation(conversationId).olderBefore,
          fetchPage: (beforeSeq, limit) =>
            chatApi.fetchEntriesBefore(conversationId, beforeSeq, limit),
          applyPage: (page) => applyConversationPage(conversationId, page),
        }),
      };
    }
    loader.current.load().catch((error: unknown) => {
      console.error(
        "[use-older-history] Failed to load older messages:",
        error,
      );
    });
  };
}
