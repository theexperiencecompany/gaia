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
  /** Everything was stopped: the running executor and every steer's pending work. */
  cancel_all?: boolean;
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
    const { conversation_id, cancel_all } = raw as ExecutorCancelledEvent;
    if (!conversation_id) return;

    // A targeted cancel cannot say which wait it ended, so it ends the oldest.
    const store = useStreamStore.getState();
    if (cancel_all) store.endAllAwaitingSessions(conversation_id);
    else store.endAwaitingSession(conversation_id);
  }, []);

  useEffect(() => {
    wsManager.on("executor.cancelled", handleCancelled);
    return () => {
      wsManager.off("executor.cancelled", handleCancelled);
    };
  }, [handleCancelled]);
}
