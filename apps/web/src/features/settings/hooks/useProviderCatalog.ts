"use client";

import { useQuery } from "@tanstack/react-query";
import {
  type ProviderCatalog,
  providersApi,
} from "@/features/settings/api/providersApi";
import { setupKeys } from "@/features/settings/api/queryKeys";
import { isSelfhostWeb } from "@/lib/selfhost";

/**
 * Provider catalog (public GET /setup/catalog): labels, endpoint defaults,
 * preset gateways and which providers can serve chat. One shared cache entry
 * for the setup wizard, the setup checklist banner and Settings → Providers & Tools.
 * Never fetched on hosted GAIA, which mounts no /setup routes.
 */
export function useProviderCatalog() {
  return useQuery<ProviderCatalog>({
    queryKey: setupKeys.catalog,
    queryFn: () => providersApi.fetchCatalog(),
    staleTime: 60_000,
    enabled: isSelfhostWeb(),
  });
}
