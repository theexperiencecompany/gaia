import type {
  ProviderCatalogResponse,
  ProviderListResponse,
  SetupStatusResponse,
} from "@gaia/shared/api/generated";
import {
  type CredentialProvider,
  type ProviderConfigBody,
  type ProviderTestResult,
  type StoredProviderConfig,
  setupTransport,
} from "@/lib/api/setupTransport";
import { api } from "@/lib/api/typed";

export type {
  CredentialProvider,
  ProviderConfigBody,
  ProviderTestResult,
  StoredProviderConfig,
};
// Wire shapes as the API serves them — aliases, never re-declarations, so the
// generator stays the single source of truth.
export type SetupStatus = SetupStatusResponse;
export type ProviderCatalog = ProviderCatalogResponse;

class ProvidersApiService {
  fetchSetupStatus(): Promise<SetupStatus> {
    return setupTransport.get<SetupStatus>("status");
  }

  fetchCatalog(): Promise<ProviderCatalog> {
    return setupTransport.get<ProviderCatalog>("catalog");
  }

  /** Stop the setup wizard opening itself for the admin. */
  dismissSetupWizard() {
    return api.post("/api/v1/setup/wizard/dismiss");
  }

  async listProviders(): Promise<ProviderListResponse["providers"]> {
    const listing = await setupTransport.get<ProviderListResponse>("providers");
    return listing.providers;
  }

  async upsertProvider(
    provider: CredentialProvider,
    body: ProviderConfigBody,
  ): Promise<void> {
    await setupTransport.put(`providers/${provider}`, body);
  }

  deleteProvider(provider: CredentialProvider): Promise<void> {
    return setupTransport.delete(`providers/${provider}`);
  }

  testProvider(
    provider: CredentialProvider,
    body?: ProviderConfigBody,
  ): Promise<ProviderTestResult> {
    return setupTransport.post<ProviderTestResult>(
      `providers/${provider}/test`,
      body ?? {},
    );
  }
}

export const providersApi = new ProvidersApiService();

/** Mirrors FAVICON_URL_TEMPLATE in app/constants/providers.py. */
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

/** Pull a human-readable message out of an axios/backend error. */
export function extractProviderError(err: unknown): string | undefined {
  if (typeof err === "object" && err !== null) {
    const data = (err as { response?: { data?: unknown } }).response?.data;
    if (typeof data === "object" && data !== null) {
      const record = data as Record<string, unknown>;
      if (typeof record.detail === "string") return record.detail;
      if (
        typeof record.detail === "object" &&
        record.detail !== null &&
        typeof (record.detail as Record<string, unknown>).message === "string"
      ) {
        return (record.detail as Record<string, unknown>).message as string;
      }
      if (typeof record.message === "string") return record.message;
    }
    if (err instanceof Error && err.message) return err.message;
  }
  return undefined;
}
