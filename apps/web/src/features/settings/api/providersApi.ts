import { apiauth } from "@/lib/api/client";

/** Providers exposed in Settings → AI Providers (mirrors CREDENTIAL_PROVIDERS). */
export type CredentialProvider =
  | "openrouter"
  | "gemini"
  | "ollama"
  | "custom"
  | "tavily";

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

class ProvidersApiService {
  async fetchSetupStatus(): Promise<SetupStatus> {
    const response = await apiauth.get<SetupStatus>("/setup/status");
    return response.data;
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
