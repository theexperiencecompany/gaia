import { apiauth } from "@/lib/api/client";

/** Providers exposed in Settings → AI Providers (mirrors CREDENTIAL_PROVIDERS). */
export type CredentialProvider =
  | "openrouter"
  | "gemini"
  | "ollama"
  | "custom"
  | "tavily";

/** All credential-backed providers, in display order (mirrors CREDENTIAL_PROVIDERS). */
export const SETUP_PROVIDER_KEYS = [
  "openrouter",
  "gemini",
  "ollama",
  "custom",
  "tavily",
] as const satisfies readonly CredentialProvider[];

export interface ProviderStatus {
  configured: boolean;
}

export interface SetupStatus {
  auth_mode: "workos" | "local";
  has_admin_account: boolean;
  needs_setup: boolean;
  /** false on self-host instances — usage is tracked but never billed. */
  billing_enabled: boolean;
  providers: Record<CredentialProvider, ProviderStatus>;
  models_seeded: boolean;
  plans_seeded: boolean;
}

export interface ProviderConfigBody {
  api_key?: string;
  base_url?: string;
  model?: string;
  /** Gateway preset for the custom lane ("opencode" | "nous"); null clears it. */
  preset?: string | null;
}

export interface ProviderTestResult {
  ok: boolean;
  detail: string;
  models: string[];
}

/** One entry of the admin-only masked provider listing (GET /setup/providers). */
export interface StoredProviderConfig {
  configured: boolean;
  /** Stored endpoint — null when unset or when only an env fallback is active. */
  base_url?: string | null;
  model?: string | null;
  /** Last four characters of the stored key; keys are never readable in full. */
  api_key_hint?: string | null;
}

class ProvidersApiService {
  async fetchSetupStatus(): Promise<SetupStatus> {
    const response = await apiauth.get<SetupStatus>("/setup/status");
    return response.data;
  }

  async listProviders(): Promise<
    Record<CredentialProvider, StoredProviderConfig>
  > {
    const response = await apiauth.get<{
      providers: Record<CredentialProvider, StoredProviderConfig>;
    }>("/setup/providers");
    return response.data.providers;
  }

  async upsertProvider(
    provider: CredentialProvider,
    body: ProviderConfigBody,
  ): Promise<void> {
    await apiauth.put(`/setup/providers/${provider}`, body);
  }

  async deleteProvider(provider: CredentialProvider): Promise<void> {
    await apiauth.delete(`/setup/providers/${provider}`);
  }

  async testProvider(
    provider: CredentialProvider,
    body?: ProviderConfigBody,
  ): Promise<ProviderTestResult> {
    const response = await apiauth.post<ProviderTestResult>(
      `/setup/providers/${provider}/test`,
      body ?? {},
    );
    return response.data;
  }
}

export const providersApi = new ProvidersApiService();

/** Mirrors FAVICON_URL_TEMPLATE in app/constants/providers.py. */
export const providerFaviconUrl = (domain: string) =>
  `https://www.google.com/s2/favicons?domain=${domain}&sz=128`;
