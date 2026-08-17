"use client";

import type { IntegrationStatusValue } from "@shared/types";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";
import { wsManager } from "@/lib/websocket/WebSocketManager";

import { integrationKeys, toolKeys } from "../api/queryKeys";

interface IntegrationStatusUpdateMessage {
  type: "integration_status_update";
  data: {
    integration_id: string;
    status: IntegrationStatusValue;
  };
}

/**
 * Keeps an open integrations page honest when a connection dies elsewhere.
 *
 * The backend broadcasts `integration_status_update` when it marks an
 * integration expired (Composio revoked the grant, or a tool call hit a dead
 * account). Without this the page keeps showing "Connected" until a manual
 * refresh — the exact failure this feature exists to remove. Invalidating
 * rather than patching the cache keeps `/integrations/me` the single source of
 * truth for the whole catalog entry, not just its status.
 */
export function useIntegrationStatusWebSocket(): void {
  const queryClient = useQueryClient();

  const handleStatusUpdate = useCallback(
    (msg: unknown) => {
      const message = msg as IntegrationStatusUpdateMessage;
      if (!message.data?.integration_id) return;

      queryClient.invalidateQueries({ queryKey: integrationKeys.all });
      queryClient.invalidateQueries({ queryKey: toolKeys.all });
    },
    [queryClient],
  );

  useEffect(() => {
    wsManager.on("integration_status_update", handleStatusUpdate);
    return () => {
      wsManager.off("integration_status_update", handleStatusUpdate);
    };
  }, [handleStatusUpdate]);
}
