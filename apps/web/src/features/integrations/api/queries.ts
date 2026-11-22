import { queryOptions } from "@tanstack/react-query";
import { fetchAvailableTools } from "@/features/chat/api/toolsApi";

import { integrationsApi } from "./integrationsApi";
import { integrationKeys, toolKeys } from "./queryKeys";

/**
 * The integration and tool reads, keyed once. A server push
 * (integration_status_update) invalidates them; nothing re-reads on a timer.
 */
export const integrationQueries = {
  mine: () =>
    queryOptions({
      queryKey: integrationKeys.me,
      queryFn: () => integrationsApi.getMyIntegrations(),
    }),
  tools: (integrationId: string) =>
    queryOptions({
      queryKey: integrationKeys.tools(integrationId),
      queryFn: () => integrationsApi.getIntegrationTools(integrationId),
    }),
  availableTools: () =>
    queryOptions({
      queryKey: toolKeys.available,
      queryFn: () => fetchAvailableTools(),
    }),
};
