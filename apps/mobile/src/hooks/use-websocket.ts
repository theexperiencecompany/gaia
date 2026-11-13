import { useEffect, useRef, useState } from "react";
import { wsManager } from "@/lib/websocket-client";

/**
 * Subscribe to a WebSocket event type and get a live `isConnected` flag; the
 * hook wires up and cleans up the subscription automatically.
 */
export function useWebSocket(
  eventType: string,
  handler: (data: unknown) => void,
): { isConnected: boolean } {
  const [isConnected, setIsConnected] = useState(wsManager.isConnected);

  // Keep a stable ref so changing the handler identity doesn't force a
  // re-subscribe on every render.
  const handlerRef = useRef(handler);
  useEffect(() => {
    handlerRef.current = handler;
  }, [handler]);

  useEffect(() => {
    // Stable wrapper that always delegates to the latest handler ref
    const stableHandler = (data: unknown) => {
      handlerRef.current(data);
    };

    const unsubscribe = wsManager.subscribe(eventType, stableHandler);

    // Mirror connection state changes into React state
    const handleConnect = () => setIsConnected(true);
    const handleDisconnect = () => setIsConnected(false);

    wsManager.onConnect(handleConnect);
    wsManager.onDisconnect(handleDisconnect);

    return () => {
      unsubscribe();
      wsManager.offConnect(handleConnect);
      wsManager.offDisconnect(handleDisconnect);
    };
  }, [eventType]);

  return { isConnected };
}
