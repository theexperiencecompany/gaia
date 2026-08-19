"use client";

import type { IntegrationStatusValue } from "@shared/types";
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import { wsManager } from "@/lib/websocket/WebSocketManager";

import { integrationKeys, toolKeys } from "../api/queryKeys";

export const INTEGRATION_STATUS_UPDATE = "integration_status_update";

interface IntegrationStatusUpdateMessage {
  type: typeof INTEGRATION_STATUS_UPDATE;
  data: {
    integration_id: string;
    status: IntegrationStatusValue;
  };
}

export type IntegrationStatusHandler = (message: unknown) => void;

/**
 * Refresh the integration caches when the backend says a connection changed.
 *
 * Invalidating rather than patching keeps `/integrations/me` the single source
 * of truth for the whole catalog entry, not just its status. A broadcast with
 * no integration id is ignored: invalidating on one would blow away the entire
 * catalog and the tool list for nothing.
 */
export function createIntegrationStatusHandler(
  queryClient: QueryClient,
): IntegrationStatusHandler {
  return (msg: unknown) => {
    const message = msg as IntegrationStatusUpdateMessage;
    if (!message.data?.integration_id) return;

    queryClient.invalidateQueries({ queryKey: integrationKeys.all });
    queryClient.invalidateQueries({ queryKey: toolKeys.all });
  };
}

/**
 * Subscribe to status broadcasts, returning the teardown for that exact handler.
 *
 * The pairing is the point: unsubscribing a different reference leaks the
 * original, and a leaked handler multiplies invalidations on every navigation.
 */
export function subscribeToIntegrationStatus(
  handler: IntegrationStatusHandler,
): () => void {
  wsManager.on(INTEGRATION_STATUS_UPDATE, handler);
  return () => {
    wsManager.off(INTEGRATION_STATUS_UPDATE, handler);
  };
}

/**
 * Keeps an open integrations page honest when a connection dies elsewhere.
 *
 * The backend broadcasts `integration_status_update` when it marks an
 * integration expired (Composio revoked the grant, or a tool call hit a dead
 * account). Without this the page keeps showing "Connected" until a manual
 * refresh — the exact failure this feature exists to remove.
 */
export function useIntegrationStatusWebSocket(): void {
  const queryClient = useQueryClient();
  const handler = useMemo(
    () => createIntegrationStatusHandler(queryClient),
    [queryClient],
  );

  useEffect(() => subscribeToIntegrationStatus(handler), [handler]);
}
