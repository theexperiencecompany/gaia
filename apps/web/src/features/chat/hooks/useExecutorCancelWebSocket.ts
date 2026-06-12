import { useCallback, useEffect } from "react";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useChatStore } from "@/stores/chatStore";

/**
 * WebSocket payload for an agent-initiated executor cancellation.
 * Emitted by the backend `cancel_executor` tool — the only signal the frontend
 * gets that a cancel it did NOT initiate (i.e. not the Stop button) happened.
 */
interface ExecutorCancelledEvent {
  type: "executor.cancelled";
  conversation_id: string;
  cancelled?: string[];
}

/**
 * Subscribe to `executor.cancelled` and clear the stuck loading indicator.
 *
 * When the agent cancels an executor task (e.g. user says "stop that"), the
 * executor-pending bridge keeps the bottom loading indicator up until its 120s
 * safety timeout — no result message arrives to clear it. This drops the bridge
 * for that conversation. (In-flight tool-card spinners are handled separately by
 * the stream-gated `isStreaming` check in `SubagentRow`: once a message's stream
 * closes, its cards stop spinning regardless of a missing end event.)
 */
export function useExecutorCancelWebSocket() {
  const handleCancelled = useCallback((raw: unknown) => {
    const { conversation_id } = raw as ExecutorCancelledEvent;
    if (!conversation_id) return;

    const store = useChatStore.getState();
    if (store.executorPendingConversationId === conversation_id) {
      store.setExecutorPendingConversationId(null);
    }
  }, []);

  useEffect(() => {
    wsManager.on("executor.cancelled", handleCancelled);
    return () => {
      wsManager.off("executor.cancelled", handleCancelled);
    };
  }, [handleCancelled]);
}
