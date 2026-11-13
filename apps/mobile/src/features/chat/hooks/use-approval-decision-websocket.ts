import { parseApprovalDecidedEvent } from "@gaia/shared/utils";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { chatDb } from "@/lib/db/chatDb";
import { wsManager } from "@/lib/websocket-client";
import { useChatStore } from "@/stores/chat-store";
import type { Message } from "../api/chat-api";
import { chatKeys } from "../api/queries";
import { applyApprovalDecisionToMessages } from "../utils/approval-status";

/**
 * Subscribe to `hil_approval_decided` and settle the matching open card,
 * mirroring web so a card decided elsewhere flips in place with no reload.
 *
 * Updates both mobile stores (the Zustand streaming map and the React Query
 * cache) and persists to AsyncStorage so the settled card survives restarts.
 */
export function useApprovalDecisionWebSocket(): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    const handleDecided = (raw: unknown): void => {
      const event = parseApprovalDecidedEvent(raw);
      if (!event) return;
      const { conversation_id: conversationId } = event;

      const store = useChatStore.getState();
      const streaming = store.messagesByConversation[conversationId];
      if (streaming) {
        const { messages: next, changed } = applyApprovalDecisionToMessages(
          streaming,
          event,
        );
        if (changed) {
          store.setMessages(conversationId, next);
          chatDb.saveMessages(conversationId, next).catch(() => undefined);
        }
      }

      const cached = queryClient.getQueryData<Message[]>(
        chatKeys.messages(conversationId),
      );
      if (cached) {
        const { messages: next, changed } = applyApprovalDecisionToMessages(
          cached,
          event,
        );
        if (changed) {
          queryClient.setQueryData(chatKeys.messages(conversationId), next);
          if (!streaming) {
            chatDb.saveMessages(conversationId, next).catch(() => undefined);
          }
        }
      }
    };

    const unsubscribe = wsManager.subscribe(
      "hil_approval_decided",
      handleDecided,
    );
    return unsubscribe;
  }, [queryClient]);
}
