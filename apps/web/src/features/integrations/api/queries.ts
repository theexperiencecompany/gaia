import { queryOptions } from "@tanstack/react-query";
import { fetchAvailableTools } from "@/features/chat/api/toolsApi";
import type { RequestOrigin } from "@/lib/api/typed";

import { integrationsApi } from "./integrationsApi";
import { integrationKeys, toolKeys } from "./queryKeys";

/**
 * The integration and tool reads, keyed once. A server push
 * (integration_status_update) invalidates them; nothing re-reads on a timer.
 */
export const integrationQueries = {
  mine: (origin?: RequestOrigin) =>
    queryOptions({
      queryKey: integrationKeys.me,
      queryFn: () => integrationsApi.getMyIntegrations(origin),
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
