"use client";
import { useEffect } from "react";

import { turnManager } from "@/features/chat/stream/turnManager";

/**
 * Re-attach to a conversation's in-flight turn after a page reload.
 *
 * When the viewed conversation changes, asks the backend whether a turn is
 * still streaming for it; if so, the turn manager attaches to the stream's
 * event log, which replays everything missed — the answer continues streaming
 * live instead of sitting on a stuck "sending" bubble until sync catches up.
 */
export const useStreamResume = (conversationId: string | null): void => {
  useEffect(() => {
    if (!conversationId) return;
    void turnManager.resumeIfActive(conversationId);
  }, [conversationId]);
};
