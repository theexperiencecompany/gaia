import { queryOptions } from "@tanstack/react-query";
import { fetchAvailableTools } from "@/features/chat/api/toolsApi";
import type { RequestOrigin } from "@/lib/api/typed";

import { integrationsApi } from "./integrationsApi";
import { integrationKeys, toolKeys } from "./queryKeys";

/**
 * The integration and tool reads, keyed once: hooks read them as the user's,
 * and the post-connect settle poll re-reads the same queries as background.
 */
export const integrationQueries = {
  snapshot: (origin?: RequestOrigin) =>
    queryOptions({
      queryKey: integrationKeys.me,
      queryFn: () => integrationsApi.getMyIntegrationsSnapshot(origin),
    }),
  statuses: (origin?: RequestOrigin) =>
    queryOptions({
      queryKey: integrationKeys.status,
      queryFn: () => integrationsApi.getIntegrationStatuses(origin),
    }),
  tools: (integrationId: string, origin?: RequestOrigin) =>
    queryOptions({
      queryKey: integrationKeys.tools(integrationId),
      queryFn: () => integrationsApi.getIntegrationTools(integrationId, origin),
    }),
  availableTools: (origin?: RequestOrigin) =>
    queryOptions({
      queryKey: toolKeys.available,
      queryFn: () => fetchAvailableTools(origin),
    }),
};
