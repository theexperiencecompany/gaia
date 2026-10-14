"use client";

import type { DeploymentStatus } from "@gaia/shared/api/generated";
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
 * entry for every consumer — the setup wizard, the setup checklist banner, the
 * settings menu/sidebar and the providers settings page.
 */
export function useSetupStatus() {
  return useQuery<SetupStatus>({
    queryKey: SETUP_STATUS_QUERY_KEY,
    queryFn: () => providersApi.fetchSetupStatus(),
    staleTime: 30_000,
  });
}

/** GAIA Cloud's profile: hosted production never serves /setup/status. */
const HOSTED_DEPLOYMENT: DeploymentStatus = {
  kind: "production",
  bills: true,
  local_code_sandbox: false,
  blob_store: "cloudinary",
  gaia_support: true,
};

/**
 * What this deployment does, from GET /setup/status; a missing status (hosted
 * production, or the probe still loading) is GAIA Cloud.
 */
export function useDeployment(): DeploymentStatus {
  const { data } = useSetupStatus();
  return data?.deployment ?? HOSTED_DEPLOYMENT;
}

export function isProviderConfigured(
  status: SetupStatus | undefined,
  key: CredentialProvider,
): boolean {
  return status?.providers?.[key]?.configured === true;
}

/** Whether a saved credential overrides a different one set in the environment. */
export function savedCredentialOverridesEnv(
  status: SetupStatus | undefined,
  key: CredentialProvider,
): boolean {
  return status?.providers?.[key]?.env_shadowed === true;
}

/**
 * Whether Settings offers a provider's card. Cloudinary does nothing unless
 * the instance stores files there (BLOB_STORE=cloudinary).
 */
export function isProviderOffered(
  status: SetupStatus | undefined,
  key: CredentialProvider,
): boolean {
  return key !== "cloudinary" || status?.deployment.blob_store === "cloudinary";
}

/**
 * The chat provider that serves requests: the first configured one in the
 * catalog's priority order, or undefined when none is.
 */
export function activeLlmProvider(
  status: SetupStatus | undefined,
  catalog: ProviderCatalog,
): CredentialProvider | undefined {
  // The catalog lists exactly the credential-store keys that can serve chat.
  const keys = catalog.llm_provider_keys as CredentialProvider[];
  return keys.find((key) => isProviderConfigured(status, key));
}

/** Whether any chat-capable provider (per the catalog) can serve a request. */
export function isAnyLlmConfigured(
  status: SetupStatus | undefined,
  catalog: ProviderCatalog,
): boolean {
  return activeLlmProvider(status, catalog) !== undefined;
}
