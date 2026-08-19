"use client";

import type { QueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { toolKeys } from "@/features/integrations/api/queryKeys";
import {
  POST_CONNECT_POLL_INTERVAL_MS,
  POST_CONNECT_POLL_MAX_ATTEMPTS,
} from "@/features/integrations/constants/connect";
import type { Integration } from "@/features/integrations/types";

interface UseSettlingPollerOptions {
  settlingIntegrationId: string | null;
  settleTick: number;
  integrations: Integration[];
  refetch: () => void;
  queryClient: QueryClient;
  onSettleDone: () => void;
  onTick: () => void;
}

export function useSettlingPoller({
  settlingIntegrationId,
  settleTick,
  integrations,
  refetch,
  queryClient,
  onSettleDone,
  onTick,
}: UseSettlingPollerOptions) {
  useEffect(() => {
    if (!settlingIntegrationId) return;

    const integration = integrations.find(
      (i) => i.id === settlingIntegrationId,
    );
    const hasSettled =
      integration?.status === "connected" && (integration?.toolCount ?? 0) > 0;

    if (hasSettled || settleTick >= POST_CONNECT_POLL_MAX_ATTEMPTS) {
      onSettleDone();
      return;
    }

    const timer = setTimeout(() => {
      refetch();
      queryClient.invalidateQueries({ queryKey: toolKeys.all });
      onTick();
    }, POST_CONNECT_POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [
    settlingIntegrationId,
    settleTick,
    integrations,
    refetch,
    queryClient,
    onSettleDone,
    onTick,
  ]);
}
