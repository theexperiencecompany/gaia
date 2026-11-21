"use client";
import { useCallback } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import { toast } from "@/lib/toast";
import { useChatStore } from "@/stores/chatStore";

/** Stop everything the open conversation runs; what was shown stays, marked stopped by the server. */
export const useStopStream = () => {
  return useCallback(async () => {
    const conversationId = useChatStore.getState().activeConversationId;
    if (!conversationId) return;
    try {
      await chatApi.stopConversation(conversationId);
    } catch (error) {
      console.error("[useStopStream] stop failed:", error);
      toast.error("Couldn't stop GAIA. Try again.");
    }
  }, []);
};
