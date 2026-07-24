import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { wsManager } from "@/lib/websocket/WebSocketManager";

import { TODAY_QUERY_KEY } from "./useTodayQuery";

/**
 * Invalidates the Today query whenever the backend broadcasts a
 * `todo.execution_status` transition (approve/answer/handoff/worker flips),
 * so the dashboard tracks GAIA's work without aggressive polling.
 */
export function useTodayLiveUpdates() {
  const queryClient = useQueryClient();

  useEffect(() => {
    const invalidate = () => {
      queryClient.invalidateQueries({ queryKey: TODAY_QUERY_KEY });
    };
    wsManager.on("todo.execution_status", invalidate);
    return () => {
      wsManager.off("todo.execution_status", invalidate);
    };
  }, [queryClient]);
}
