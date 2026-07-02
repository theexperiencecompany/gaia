"use client";
import { useEffect } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import { turnManager } from "@/features/chat/stream/turnManager";
import { applySyncedConversation } from "@/services/syncService";

/**
 * Reconcile a conversation with the server when it's opened — one request:
 * the sync fetch also carries the active-stream verdict, resume consumes
 * that verdict, and only then are the fetched messages applied.
 *
 * Order is load-bearing. The verdict says whether a turn is still streaming
 * and, if so, resume attaches to its event log (replaying everything missed)
 * — registering a live session. Only THEN are the fetched messages applied:
 * mid-turn the server hasn't persisted the turn's messages yet, so an apply
 * that ran ahead of resume would see no server copy of the user's optimistic
 * message and sweep it as an orphan — the "my message vanished until the
 * stream finished" bug. With a session registered, the apply is blocked for
 * the streaming conversation; with no live turn, it proceeds and any orphan
 * sweep is legitimate.
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
