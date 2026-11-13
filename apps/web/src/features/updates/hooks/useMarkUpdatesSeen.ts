import { useEffect } from "react";
import { OUTBOX_MESSAGE_EVENT } from "@/lib/websocket/outboxEvents";
import { wsManager } from "@/lib/websocket/WebSocketManager";
import { useUpdatesSeenStore } from "../stores/updatesSeenStore";

/** Counts everything on the page as seen: on arrival, as it is told while the page is open, and on leaving. */
export function useMarkUpdatesSeen() {
  const markSeen = useUpdatesSeenStore((state) => state.markSeen);

  useEffect(() => {
    markSeen();
    wsManager.on(OUTBOX_MESSAGE_EVENT, markSeen);
    return () => {
      wsManager.off(OUTBOX_MESSAGE_EVENT, markSeen);
      markSeen();
    };
  }, [markSeen]);
}
