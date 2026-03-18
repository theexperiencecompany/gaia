import { useEffect, useRef, useState } from "react";
import { wsManager } from "@/lib/websocket-client";

/**
 * Subscribe to a specific WebSocket event type and receive a live
 * `isConnected` flag reflecting the current connection state.
 *
 * The hook wires up / cleans up the subscription automatically so callers
 * never need to interact with the manager directly.
 *
 * @example
 * ```tsx
 * const { isConnected } = useWebSocket('notification.delivered', (data) => {
 *   console.log('New notification', data);
 * });
 * ```
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
