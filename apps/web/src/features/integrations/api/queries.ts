import { queryOptions } from "@tanstack/react-query";
import { fetchAvailableTools } from "@/features/chat/api/toolsApi";

import { integrationsApi } from "./integrationsApi";
import { integrationKeys, toolKeys } from "./queryKeys";

/** The integration and tool reads, keyed once. */
export const integrationQueries = {
  snapshot: () =>
    queryOptions({
      queryKey: integrationKeys.me,
      queryFn: () => integrationsApi.getMyIntegrationsSnapshot(),
    }),
  statuses: () =>
    queryOptions({
      queryKey: integrationKeys.status,
      queryFn: () => integrationsApi.getIntegrationStatuses(),
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
