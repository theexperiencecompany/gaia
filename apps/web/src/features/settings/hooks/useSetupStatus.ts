"use client";

import type {
  DeploymentStatus,
  ProviderFeature,
} from "@gaia/shared/api/generated";
import { useQuery } from "@tanstack/react-query";
import {
  type CredentialProvider,
  type ProviderCatalog,
  providersApi,
  type SetupStatus,
} from "@/features/settings/api/providersApi";
import { isSelfhostWeb } from "@/lib/selfhost";

const SETUP_STATUS_QUERY_KEY = ["setup", "status"] as const;

/**
 * Instance setup status (public endpoint). Single shared react-query cache
 * entry for every consumer — the setup wizard, the setup checklist banner, the
 * settings menu/sidebar and the providers settings page. Never fetched on
 * hosted GAIA, which mounts no /setup routes.
 */
export function useSetupStatus() {
  return useQuery<SetupStatus>({
    queryKey: SETUP_STATUS_QUERY_KEY,
    queryFn: () => providersApi.fetchSetupStatus(),
    staleTime: 30_000,
    enabled: isSelfhostWeb(),
  });
}

/** GAIA Cloud's profile; hosted GAIA never serves /setup/status. */
const HOSTED_DEPLOYMENT: DeploymentStatus = {
  kind: "production",
  bills: true,
  local_code_sandbox: false,
  blob_store: "cloudinary",
  gaia_support: true,
  instance_toolkits: false,
  private_network_endpoints: false,
};

/** A self-hosted instance's baseline profile (ENV=selfhost with nothing optional set). */
const SELFHOST_DEPLOYMENT: DeploymentStatus = {
  kind: "selfhost",
  bills: false,
  local_code_sandbox: false,
  blob_store: "local",
  gaia_support: false,
  instance_toolkits: true,
  private_network_endpoints: true,
};

/**
 * What this deployment does, from GET /setup/status; until it loads, the
 * build's own profile, so hosted and self-host are each right from first paint.
 */
export function useDeployment(): DeploymentStatus {
  const { data } = useSetupStatus();
  if (data) return data.deployment;
  return isSelfhostWeb() ? SELFHOST_DEPLOYMENT : HOSTED_DEPLOYMENT;
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

/** Whether a feature works right now, on a saved provider or its built-in engine. */
export function isFeatureWorking(
  status: SetupStatus | undefined,
  feature: ProviderFeature,
): boolean {
  return status?.features[feature]?.working === true;
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
