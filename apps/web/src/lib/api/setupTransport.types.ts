/** Wire shapes for the runtime provider-credential endpoints.

Kept here (not in the generated contract): the /setup responses are assembled
per-request from the live credential collection, so the generated types are
narrower than what the instance actually answers.
 */
/** Providers whose credentials the credential store can hold. */
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

/** Gateway preset for the custom OpenAI-compatible lane; null clears it. */
export type CustomPresetKey = "opencode" | "nous";

export interface ProviderConfigBody {
  api_key?: string;
  base_url?: string;
  model?: string;
  preset?: CustomPresetKey | null;
}

export interface ProviderTestResult {
  ok: boolean;
  detail: string;
  models: string[];
}

/** One entry of the admin-only masked provider listing. */
export interface StoredProviderConfig {
  configured: boolean;
  /** Stored endpoint — null when unset or when only an env fallback is active. */
  base_url?: string | null;
  model?: string | null;
  /** Last four characters of the stored key; keys are never readable in full. */
  api_key_hint?: string | null;
}
