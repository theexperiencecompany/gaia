"use client";
import { useEffect } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import { turnManager } from "@/features/chat/stream/turnManager";
import { db } from "@/lib/db/chatDb";
import { applySyncedConversation } from "@/services/syncService";

/**
 * Reconcile a conversation on open: one sync fetch returns the active-stream
 * verdict and, only when the server's copy is newer than the cached one, the
 * messages. A long chat (a bot DM) is downloaded once, not on every open.
 *
 * Order is load-bearing — resume must attach to a live turn's event log
 * before messages apply, or an apply that runs ahead sweeps the optimistic
 * user message as an orphan (the "message vanished" bug).
 */
export const useStreamResume = (conversationId: string | null): void => {
  useEffect(() => {
    if (!conversationId) return;
    const resumeThenApply = async (): Promise<void> => {
      // Without a usable cached timestamp last_updated is undefined, which makes
      // the backend return the full conversation. A legacy row can hold an
      // invalid date, and serializing that would throw before the resume.
      const cached = await db.getConversation(conversationId);
      const cachedAt = cached?.updatedAt;
      const { conversations, active_streams } =
        await chatApi.batchSyncConversations([
          {
            conversation_id: conversationId,
            last_updated:
              cachedAt && !Number.isNaN(cachedAt.getTime())
                ? cachedAt.toISOString()
                : undefined,
          },
        ]);
      const conversation = conversations.at(0);
      // resumeIfActive never rejects (attach failures are logged internally).
      // A conversation the server does not have cannot have a live turn.
      await turnManager.resumeIfActive(
        conversationId,
        active_streams[conversationId] ?? null,
      );
      if (conversation) {
        await applySyncedConversation(conversationId, conversation);
      }
    };
    resumeThenApply().catch((error) => {
      console.error("[useStreamResume] resume-and-sync failed:", error);
    });
  }, [conversationId]);
};
