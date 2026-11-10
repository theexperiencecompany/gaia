"use client";

import { useQuery } from "@tanstack/react-query";
import { providersApi } from "@/features/settings/api/providersApi";
import { setupKeys } from "@/features/settings/api/queryKeys";

/**
 * Admin-only masked provider listing (GET /setup/providers) — the stored
 * base_url/model/key-hint per provider, as saved in the credential store.
 * Feeds the provider credential forms so they seed from what is actually
 * stored instead of catalog defaults.
 */
export function useProviderConfigs() {
  return useQuery({
    queryKey: setupKeys.providers,
    queryFn: () => providersApi.listProviders(),
    staleTime: 30_000,
  });
}
