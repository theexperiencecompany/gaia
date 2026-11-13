import {
  parseApprovalDecidedEvent,
  settleApprovalToolData,
} from "@shared/utils";
import { useCallback, useEffect } from "react";
import { db } from "@/lib/db/chatDb";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useChatStore } from "@/stores/chatStore";

/**
 * Subscribe to `hil_approval_decided` and settle the matching open card.
 *
 * Without this, a card decided anywhere but the open tab — another device, the
 * review sheet on a different message, an agent-side revoke — stays actionable
 * forever. Writes back through IndexedDB + the store so the card settles (or
 * the tombstone appears) with no reload.
 */
export function useApprovalDecisionWebSocket() {
  const handleDecided = useCallback(async (raw: unknown) => {
    const event = parseApprovalDecidedEvent(raw);
    if (!event) return;

    const messages =
      useChatStore.getState().messagesByConversation[event.conversation_id] ??
      [];
    // Approval ids are unique, so at most one message carries the card.
    const updated = messages
      .map((message) => {
        const { entries, changed } = settleApprovalToolData(
          message.tool_data,
          event,
        );
        return changed ? { ...message, tool_data: entries } : null;
      })
      .find((message) => message !== null);
    if (!updated) return;
    try {
      await db.putMessage(updated);
    } catch (err) {
      console.error(
        "[useApprovalDecisionWebSocket] Failed to persist card:",
        err,
      );
    }
    useChatStore.getState().addOrUpdateMessage(updated);
  }, []);

  useEffect(() => {
    wsManager.on("hil_approval_decided", handleDecided);
    return () => {
      wsManager.off("hil_approval_decided", handleDecided);
    };
  }, [handleDecided]);
}
