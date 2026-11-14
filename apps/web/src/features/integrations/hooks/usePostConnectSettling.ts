import { useCallback, useState } from "react";

import type { Integration } from "../types";

/**
 * The OAuth callback redirects as soon as tokens are stored; the MCP handshake
 * and tools/list finish in the background, and the server pushes
 * integration_status_update once the tools are stored (or the connect fell
 * back to created). The just-connected integration is "settling" while the
 * catalog reports it connected with no tools yet.
 */
export function usePostConnectSettling(integrations: Integration[]) {
  const [connectedId, setConnectedId] = useState<string | null>(null);

  const integration = integrations.find((i) => i.id === connectedId);
  const settlingIntegrationId =
    integration?.status === "connected" && (integration.toolCount ?? 0) === 0
      ? integration.id
      : null;

  const beginSettling = useCallback((integrationId: string) => {
    setConnectedId(integrationId);
  }, []);

  return { beginSettling, settlingIntegrationId };
}
