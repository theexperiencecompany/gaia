"use client";

import { useCallback, useEffect, useRef } from "react";

import type { Integration } from "../types";

/**
 * Integration opened from a deep link / marketplace add before its catalog
 * entry has loaded (the refetch may still be in flight). It is opened
 * immediately when already listed; otherwise the id waits in a ref — not
 * state, nothing renders from it — until a refreshed catalog contains it.
 */
export function usePendingDeepLink(
  integrations: Integration[],
  onOpen: (integrationId: string) => void,
) {
  const pendingDeepLinkId = useRef<string | null>(null);
  const isInCatalog = useCallback(
    (integrationId: string) => integrations.some((i) => i.id === integrationId),
    [integrations],
  );

  useEffect(() => {
    const pending = pendingDeepLinkId.current;
    if (!pending || !isInCatalog(pending)) return;
    pendingDeepLinkId.current = null;
    onOpen(pending);
  }, [isInCatalog, onOpen]);

  const markPending = useCallback(
    (integrationId: string) => {
      if (isInCatalog(integrationId)) {
        onOpen(integrationId);
        return;
      }
      pendingDeepLinkId.current = integrationId;
    },
    [isInCatalog, onOpen],
  );

  return { markPending };
}
