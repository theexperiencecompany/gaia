import type {
  CredentialProviderName,
  MaskedProvider,
  ProviderCatalogResponse,
  ProviderCredentialBody,
  ProviderTestResponse,
  SetupStatusResponse,
} from "@shared/api/generated";
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
