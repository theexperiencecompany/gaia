"use client";
import { useEffect } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import { db } from "@/lib/db/chatDb";
import { applySyncedConversation } from "@/services/syncService";

/**
 * Refresh a conversation's stored row and saved messages on open. One sync fetch
 * returns the messages only when the server's copy is newer than the cached one,
 * so a long chat (a bot DM) is downloaded once, not on every open.
 */
export const useConversationSync = (conversationId: string | null): void => {
  useEffect(() => {
    if (!conversationId) return;
    const sync = async (): Promise<void> => {
      // A legacy row can hold an invalid date; serializing it would throw.
      const cachedAt = (await db.getConversation(conversationId))?.updatedAt;
      const { conversations } = await chatApi.batchSyncConversations([
        {
          conversation_id: conversationId,
          last_updated:
            cachedAt && !Number.isNaN(cachedAt.getTime())
              ? cachedAt.toISOString()
              : undefined,
        },
      ]);
      const conversation = conversations.at(0);
      if (conversation) {
        await applySyncedConversation(conversationId, conversation);
      }
    };
    sync().catch((error) => {
      console.error("[useConversationSync] sync failed:", error);
    });
  }, [conversationId]);
};
