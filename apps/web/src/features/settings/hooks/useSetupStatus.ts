"use client";

import { useQuery } from "@tanstack/react-query";
import {
  type CredentialProvider,
  type ProviderCatalog,
  providersApi,
  type SetupStatus,
} from "@/features/settings/api/providersApi";

const SETUP_STATUS_QUERY_KEY = ["setup", "status"] as const;

/**
 * Instance setup status (public endpoint). Single shared react-query cache
 * entry for every consumer — the setup wizard, the checklist card, the
 * settings menu/sidebar and the providers settings page.
 */
export function useSetupStatus() {
  return useQuery<SetupStatus>({
    queryKey: SETUP_STATUS_QUERY_KEY,
    queryFn: () => providersApi.fetchSetupStatus(),
    staleTime: 30_000,
  });
}

export function isProviderConfigured(
  status: SetupStatus | undefined,
  key: CredentialProvider,
): boolean {
  return status?.providers?.[key]?.configured === true;
}

/** Whether any chat-capable provider (per the catalog) can serve a request. */
export function isAnyLlmConfigured(
  status: SetupStatus | undefined,
  catalog: ProviderCatalog,
): boolean {
  return catalog.llm_provider_keys.some(
    (key) => status?.providers?.[key]?.configured === true,
  );
}
