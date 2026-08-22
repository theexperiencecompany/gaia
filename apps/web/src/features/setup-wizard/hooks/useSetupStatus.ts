"use client";

import { useQuery } from "@tanstack/react-query";
import {
  type CredentialProvider,
  providersApi,
  type SetupStatus,
} from "@/features/settings/api/providersApi";
import { SETUP_PROVIDER_KEYS } from "../types";

export const SETUP_STATUS_QUERY_KEY = ["setup", "status"] as const;

/**
 * Instance setup status (public endpoint). Exposed via react-query so the
 * wizard, the checklist card and any future caller share one cache entry.
 */
export function useSetupStatus(options?: { enabled?: boolean }) {
  return useQuery<SetupStatus>({
    queryKey: SETUP_STATUS_QUERY_KEY,
    queryFn: () => providersApi.fetchSetupStatus(),
    staleTime: 30_000,
    enabled: options?.enabled ?? true,
  });
}

export function isProviderConfigured(
  status: SetupStatus | undefined,
  key: CredentialProvider,
): boolean {
  return status?.providers?.[key]?.configured === true;
}

export function isAnyLlmConfigured(status: SetupStatus | undefined): boolean {
  return SETUP_PROVIDER_KEYS.some((key) =>
    key === "tavily" ? false : isProviderConfigured(status, key),
  );
}
