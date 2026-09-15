"use client";
import { useEffect } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import { turnManager } from "@/features/chat/stream/turnManager";
import { applySyncedConversation } from "@/services/syncService";

/**
 * Reconcile a conversation on open: one sync fetch returns the active-stream
 * verdict and the messages.
 *
 * Order is load-bearing — resume must attach to a live turn's event log
 * before messages apply, or an apply that runs ahead sweeps the optimistic
 * user message as an orphan (the "message vanished" bug).
 */
export const useStreamResume = (conversationId: string | null): void => {
  useEffect(() => {
    if (!conversationId) return;
    const resumeThenApply = async (): Promise<void> => {
      // Sending undefined for last_updated forces the backend to return the
      // full conversation, alongside its active-stream verdict.
      const { conversations } = await chatApi.batchSyncConversations([
        { conversation_id: conversationId, last_updated: undefined },
      ]);
      const conversation = conversations.at(0);
      // resumeIfActive never rejects (attach failures are logged internally).
      // A missing conversation cannot have a live turn — null verdict.
      await turnManager.resumeIfActive(
        conversationId,
        conversation?.active_stream_id ?? null,
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
