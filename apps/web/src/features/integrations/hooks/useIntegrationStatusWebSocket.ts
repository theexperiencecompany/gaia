"use client";

import type { IntegrationStatusValue } from "@shared/types";
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { wsManager } from "@/lib/websocket/WebSocketManager";

import { invalidateIntegrationCaches } from "../api/queryKeys";

export const INTEGRATION_STATUS_UPDATE = "integration_status_update";

interface IntegrationStatusUpdateMessage {
  type: typeof INTEGRATION_STATUS_UPDATE;
  data: {
    integration_id: string;
    status: IntegrationStatusValue;
  };
}

type IntegrationStatusHandler = (message: unknown) => void;

/**
 * Refresh the integration caches when the backend says a connection changed.
 *
 * Invalidating rather than patching keeps the catalog snapshot and status map
 * in sync. A broadcast with no integration id is ignored: invalidating on one
 * would blow away the entire catalog and the tool list for nothing.
 */
export function createIntegrationStatusHandler(
  queryClient: QueryClient,
): IntegrationStatusHandler {
  return (msg: unknown) => {
    const message = msg as IntegrationStatusUpdateMessage;
    if (!message.data?.integration_id) return;

    invalidateIntegrationCaches(queryClient);
  };
}

/**
 * Subscribe to status broadcasts and socket (re)connects, returning the teardown
 * for those exact handlers.
 *
 * A broadcast sent while the socket was down (an OAuth round trip, a network
 * drop) is never replayed, so every (re)connect re-reads the caches. Unsubscribing
 * a different reference leaks the original and multiplies invalidations.
 */
export function subscribeToIntegrationStatus(
  queryClient: QueryClient,
): () => void {
  const onStatus = createIntegrationStatusHandler(queryClient);
  const onConnect = () => invalidateIntegrationCaches(queryClient);
  wsManager.on(INTEGRATION_STATUS_UPDATE, onStatus);
  wsManager.onConnect(onConnect);
  return () => {
    wsManager.off(INTEGRATION_STATUS_UPDATE, onStatus);
    wsManager.offConnect(onConnect);
  };
}

/**
 * Keeps every open page's integration and tool caches honest, app-wide.
 *
 * The backend broadcasts `integration_status_update` on connect, again once an
 * MCP's tools are stored (they are discovered after the connect returns), and
 * when it marks an integration expired. Mounted once in the app shell.
 */
export function useIntegrationStatusWebSocket(): void {
  const queryClient = useQueryClient();

  useEffect(() => subscribeToIntegrationStatus(queryClient), [queryClient]);
}
