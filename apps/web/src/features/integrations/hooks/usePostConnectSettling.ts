import { useCallback, useEffect, useState } from "react";

import { POST_CONNECT_SETTLE_TIMEOUT_MS } from "../constants/connect";
import type { Integration } from "../types";

/**
 * Which just-connected integration is still waiting for its tools.
 *
 * Tools land after the connect returns; the integration_status_update broadcast
 * refetches the catalog when they do, which ends this state. When they never
 * arrive it ends after POST_CONNECT_SETTLE_TIMEOUT_MS.
 */
export function usePostConnectSettling(integrations: Integration[]) {
  // A fresh object per connect, so reconnecting the same id restarts the wait.
  const [pending, setPending] = useState<{ integrationId: string } | null>(
    null,
  );

  useEffect(() => {
    if (!pending) return;
    const timer = setTimeout(
      () => setPending(null),
      POST_CONNECT_SETTLE_TIMEOUT_MS,
    );
    return () => clearTimeout(timer);
  }, [pending]);

  const beginSettling = useCallback((integrationId: string) => {
    setPending({ integrationId });
  }, []);

  const integration = pending
    ? integrations.find((i) => i.id === pending.integrationId)
    : undefined;
  const hasTools =
    integration?.status === "connected" && (integration.toolCount ?? 0) > 0;
  const settlingIntegrationId =
    pending && !hasTools ? pending.integrationId : null;

  return { beginSettling, settlingIntegrationId };
}
