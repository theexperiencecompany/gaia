import { useCallback } from "react";
import { useChatStore } from "@/stores/chatStore";
import { useStreamStore } from "@/stores/streamStore";

/**
 * Clear a conversation's "waiting on you" gate the moment the user decides,
 * before the resolved stream frame arrives.
 *
 * Prefers the caller's conversation (a sheet or background card outlives the
 * active one), then `activeConversationId`, then the pending new-chat key —
 * the route param is stale for a replaceState'd new chat.
 */
export function useMarkApprovalDecided(): (conversationId?: string) => void {
  const clearAwaitingApproval = useStreamStore(
    (state) => state.clearAwaitingApproval,
  );
  return useCallback(
    (conversationId?: string) => {
      const key =
        conversationId ??
        useChatStore.getState().activeConversationId ??
        useStreamStore.getState().pendingNewConversationKey;
      if (key) clearAwaitingApproval(key);
    },
    [clearAwaitingApproval],
  );
}
