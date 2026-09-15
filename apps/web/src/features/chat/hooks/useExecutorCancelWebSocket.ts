import { useCallback, useEffect } from "react";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useStreamStore } from "@/stores/streamStore";

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
 * An agent-initiated cancel (e.g. "stop that") has no result message to end
 * the awaiting-executor session, so this drops it. Tool-card spinners are
 * handled separately by `isStreaming` in `SubagentRow`.
 */
export function useExecutorCancelWebSocket() {
  const handleCancelled = useCallback((raw: unknown) => {
    const { conversation_id } = raw as ExecutorCancelledEvent;
    if (!conversation_id) return;

    const state = useStreamStore.getState();
    if (state.sessions[conversation_id]?.phase === "awaiting_executor") {
      state.endSession(conversation_id);
    }
  }, []);

  useEffect(() => {
    wsManager.on("executor.cancelled", handleCancelled);
    return () => {
      wsManager.off("executor.cancelled", handleCancelled);
    };
  }, [handleCancelled]);
}
