import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { integrationQueries } from "../api/queries";
import {
  POST_CONNECT_POLL_INTERVAL_MS,
  POST_CONNECT_POLL_MAX_ATTEMPTS,
} from "../constants/connect";
import type { Integration } from "../types";

/**
 * The OAuth callback redirects as soon as tokens are stored; the MCP handshake
 * and tools/list run in the background, so a connected integration's tools land
 * a few seconds later. Poll the personalized /integrations/me catalog until the
 * integration reports connected with discovered tools (or give up) instead of
 * forcing a page reload. Re-runs whenever a refetch updates `integrations`.
 */
export function usePostConnectSettlePolling(integrations: Integration[]) {
  const queryClient = useQueryClient();
  // Integration whose tools are still being discovered after a successful
  // connect — drives bounded polling and the sidebar's "Setting up tools" state.
  const [settlingIntegrationId, setSettlingIntegrationId] = useState<
    string | null
  >(null);
  // Incremented on each poll so the effect re-runs every interval even when the
  // refetched data is byte-identical (react-query structural sharing keeps the
  // same `integrations` reference until tools actually land).
  const [settleTick, setSettleTick] = useState(0);

  useEffect(() => {
    if (!settlingIntegrationId) return;

    const integration = integrations.find(
      (i) => i.id === settlingIntegrationId,
    );
    const hasSettled =
      integration?.status === "connected" && (integration?.toolCount ?? 0) > 0;

    // Stop once the integration connects with tools, or after the attempt
    // ceiling (covers a failed background connect) — keep polling meanwhile,
    // since the post-connect refetch may still be in flight.
    if (hasSettled || settleTick >= POST_CONNECT_POLL_MAX_ATTEMPTS) {
      setSettlingIntegrationId(null);
      return;
    }

    const timer = setTimeout(() => {
      // The user connected already; these re-reads are the poll's, not theirs.
      const background = { background: true };
      void queryClient.prefetchQuery({
        ...integrationQueries.snapshot(background),
        staleTime: 0,
      });
      void queryClient.prefetchQuery({
        ...integrationQueries.statuses(background),
        staleTime: 0,
      });
      void queryClient.prefetchQuery({
        ...integrationQueries.tools(settlingIntegrationId, background),
        staleTime: 0,
      });
      void queryClient.prefetchQuery({
        ...integrationQueries.availableTools(background),
        staleTime: 0,
      });
      setSettleTick((tick) => tick + 1);
    }, POST_CONNECT_POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [settlingIntegrationId, settleTick, integrations, queryClient]);

  const beginSettling = useCallback((integrationId: string) => {
    setSettlingIntegrationId(integrationId);
    setSettleTick(0);
  }, []);

  return { beginSettling, settlingIntegrationId };
}
