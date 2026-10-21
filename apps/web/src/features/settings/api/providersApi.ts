import type {
  CredentialProviderName,
  MaskedProvider,
  ProviderCatalogResponse,
  ProviderCredentialBody,
  ProviderTestResponse,
  SetupStatusResponse,
} from "@gaia/shared/api/generated";
import { api } from "@/lib/api/typed";

// Wire shapes as the API serves them — aliases, never re-declarations, so the
// generator stays the single source of truth.
export type SetupStatus = SetupStatusResponse;
export type ProviderCatalog = ProviderCatalogResponse;
export type CredentialProvider = CredentialProviderName;
export type ProviderConfigBody = ProviderCredentialBody;
export type ProviderTestResult = ProviderTestResponse;
export type StoredProviderConfig = MaskedProvider;

const PROVIDER_PATH = "/api/v1/setup/providers/{provider}";

// Background reads stay silent; writes and probes render their errors inline.
class ProvidersApiService {
  fetchSetupStatus(): Promise<SetupStatus> {
    return api.get("/api/v1/setup/status", { silent: true });
  }

  fetchCatalog(): Promise<ProviderCatalog> {
    return api.get("/api/v1/setup/catalog", { silent: true });
  }

  /** Stop the setup wizard opening itself for the admin. */
  dismissSetupWizard() {
    return api.post("/api/v1/setup/wizard/dismiss");
  }

  async listProviders() {
    const listing = await api.get("/api/v1/setup/providers", { silent: true });
    return listing.providers;
  }

  async upsertProvider(
    provider: CredentialProvider,
    body: ProviderConfigBody,
  ): Promise<void> {
    await api.put(PROVIDER_PATH, { path: { provider }, body, silent: true });
  }

  async deleteProvider(provider: CredentialProvider): Promise<void> {
    await api.delete(PROVIDER_PATH, { path: { provider }, silent: true });
  }

  testProvider(
    provider: CredentialProvider,
    body: ProviderConfigBody = {},
  ): Promise<ProviderTestResult> {
    return api.post("/api/v1/setup/providers/{provider}/test", {
      path: { provider },
      body,
      silent: true,
    });
  }
}

export const providersApi = new ProvidersApiService();

/** A provider's logo, from its domain. */
export const providerFaviconUrl = (domain: string) =>
  `https://www.google.com/s2/favicons?domain=${domain}&sz=128`;

/**
 * Map a raw provider error detail to an actionable recovery hint. Returns
 * null when the detail already contains its own guidance (private URL) or
 * when no specific hint applies — caller should show the original detail
 * plus this hint below it.
 */
export function getProviderErrorHint(
  detail: string,
  keyUrl: string,
): string | null {
  const lower = detail.toLowerCase();
  // Private / unreachable already carries _PRIVATE_URL_HINT — keep that as-is.
  if (lower.includes("private") || lower.includes("unreachable")) return null;
  if (
    lower.includes("401") ||
    lower.includes("invalid") ||
    lower.includes("unauthorized")
  ) {
    if (keyUrl) {
      return `Check your API key at ${keyUrl} — it may be expired or missing permissions.`;
    }
    return "Check your API key — it may be expired or missing permissions.";
  }
  if (lower.includes("429") || lower.includes("rate")) {
    return "Rate limited — wait a minute and try again, or check your plan limits.";
  }
  if (lower.includes("timeout") || lower.includes("timed out")) {
    return "Provider didn't respond — check your network or try again.";
  }
  return null;
}

/** The API's own words for a failed setup call (the error envelope's message). */
export function extractProviderError(err: unknown): string | undefined {
  return err instanceof Error && err.message ? err.message : undefined;
}
