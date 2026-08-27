import { apiauth } from "@/lib/api/client";

/** Providers exposed in Settings → AI Providers (mirrors CREDENTIAL_PROVIDERS). */
export type CredentialProvider =
  | "openrouter"
  | "gemini"
  | "ollama"
  | "custom"
  | "tavily"
  | "composio"
  | "e2b"
  | "openai"
  | "resend"
  | "cloudinary"
  | "google_oauth"
  | "firecrawl";

/** Providers that can serve chat (mirrors _LLM_PROVIDER_KEYS in
 * app/api/v1/endpoints/setup.py). The tool/integration keys in
 * SETUP_PROVIDER_KEYS must never count toward LLM readiness. */
export const LLM_PROVIDER_KEYS = [
  "openrouter",
  "gemini",
  "ollama",
  "custom",
] as const satisfies readonly CredentialProvider[];

/**
 * OpenAI-compatible preset gateways surfaced as chips inside the "custom"
 * lane — paste an API key and go. Single catalog shared by Settings and the
 * setup wizard (mirrors the opencode/nous entries of PRESETS in
 * app/constants/providers.py; the backend stays the source of truth).
 */
export interface CustomPreset {
  /** Gateway id sent as `preset` on ProviderConfigBody. */
  key: "opencode" | "nous";
  label: string;
  baseUrl: string;
  /** Empty ⇒ fetched from the endpoint at configure time. */
  defaultModel: string;
  faviconDomain: string;
}

export const CUSTOM_PRESETS: readonly CustomPreset[] = [
  {
    key: "opencode",
    label: "OpenCode",
    baseUrl: "https://opencode.ai/zen/go/v1",
    defaultModel: "deepseek-v4-flash",
    faviconDomain: "opencode.ai",
  },
  {
    key: "nous",
    label: "Nous Research",
    baseUrl: "https://inference-api.nousresearch.com/v1",
    defaultModel: "",
    faviconDomain: "nousresearch.com",
  },
];

/** Direct link to obtain an API key for providers that use one. */
export const PROVIDER_KEY_URLS: Partial<Record<CredentialProvider, string>> = {
  openrouter: "https://openrouter.ai/keys",
  gemini: "https://aistudio.google.com/apikey",
  tavily: "https://app.tavily.com",
  composio: "https://app.composio.dev",
  firecrawl: "https://www.firecrawl.dev/app/api-keys",
  resend: "https://resend.com/api-keys",
  cloudinary: "https://console.cloudinary.com/settings/api-keys",
};

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
  plans_seeded: boolean;
}

export interface ProviderConfigBody {
  api_key?: string;
  base_url?: string;
  model?: string;
  /** Gateway preset for the custom lane; null clears it. */
  preset?: CustomPreset["key"] | null;
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

export interface CatalogProviderMeta {
  label: string;
  description?: string;
  favicon_domain: string;
  needs_base_url: boolean;
  default_model: string;
  default_base_url?: string;
  base_url?: string;
}

export interface ProviderCatalog {
  providers: Record<CredentialProvider, CatalogProviderMeta>;
  custom_presets: Record<string, CatalogProviderMeta>;
  llm_provider_keys: CredentialProvider[];
}

class ProvidersApiService {
  async fetchSetupStatus(): Promise<SetupStatus> {
    const response = await apiauth.get<SetupStatus>("/setup/status");
    return response.data;
  }

  async fetchCatalog(): Promise<ProviderCatalog> {
    const response = await apiauth.get<ProviderCatalog>("/setup/catalog");
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

/**
 * Map a raw provider error detail to an actionable recovery hint. Returns
 * null when the detail already contains its own guidance (private URL) or
 * when no specific hint applies — caller should show the original detail
 * plus this hint below it.
 */
export function getProviderErrorHint(
  detail: string,
  providerKey?: CredentialProvider,
): string | null {
  const lower = detail.toLowerCase();
  // Private / unreachable already carries _PRIVATE_URL_HINT — keep that as-is.
  if (lower.includes("private") || lower.includes("unreachable")) return null;
  if (
    lower.includes("401") ||
    lower.includes("invalid") ||
    lower.includes("unauthorized")
  ) {
    const url = providerKey
      ? (PROVIDER_KEY_URLS as Record<string, string>)[providerKey]
      : undefined;
    if (url) {
      return `Check your API key at ${url} — it may be expired or missing permissions.`;
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
