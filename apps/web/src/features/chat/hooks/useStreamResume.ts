"use client";
import { useEffect } from "react";

import { turnManager } from "@/features/chat/stream/turnManager";
import { syncSingleConversation } from "@/services/syncService";

/**
 * Reconcile a conversation with the server when it's opened: resume first,
 * then sync.
 *
 * Order is load-bearing. Resume asks the backend whether a turn is still
 * streaming and, if so, attaches to its event log (replaying everything
 * missed) — registering a live session. Only THEN does the freshness sync
 * run: mid-turn the server hasn't persisted the turn's messages yet, so a
 * sync that races ahead of resume would see no server copy of the user's
 * optimistic message and sweep it as an orphan — the "my message vanished
 * until the stream finished" bug. With a session registered, the sync is
 * blocked for the streaming conversation; with no live turn, it proceeds
 * and any orphan sweep is legitimate.
 */
export const useStreamResume = (conversationId: string | null): void => {
  useEffect(() => {
    if (!conversationId) return;
    // resumeIfActive never rejects (discovery failures are logged internally).
    void turnManager.resumeIfActive(conversationId).then(() => {
      syncSingleConversation(conversationId).catch((error) => {
        console.error("[useStreamResume] post-resume sync failed:", error);
      });
    });
  }, [conversationId]);
};
