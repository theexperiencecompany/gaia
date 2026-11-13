import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { OUTBOX_MESSAGE_EVENT } from "@/lib/websocket/outboxEvents";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { updatesKeys } from "../api/queryKeys";

export function useUpdatesLiveRefresh() {
  const queryClient = useQueryClient();

  useEffect(() => {
    const refresh = () =>
      queryClient.invalidateQueries({ queryKey: updatesKeys.all });

    wsManager.on(OUTBOX_MESSAGE_EVENT, refresh);
    return () => wsManager.off(OUTBOX_MESSAGE_EVENT, refresh);
  }, [queryClient]);
}
