"use client";
import { useCallback } from "react";

import { turnManager } from "@/features/chat/stream/turnManager";
import { useChatStore } from "@/stores/chatStore";

/** Abort the active conversation's turn (persists progress, cancels backend). */
export const useStopStream = () => {
  return useCallback(async () => {
    await turnManager.stop(useChatStore.getState().activeConversationId);
  }, []);
};
