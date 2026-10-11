import type {
  MaskedProvider,
  ProviderCredentialBody,
  ProviderTestResponse,
} from "@gaia/shared/api/generated";

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

// Wire shapes as the API serves them — aliases, never re-declarations, so the
// generator stays the single source of truth.
export type ProviderConfigBody = ProviderCredentialBody;
export type ProviderTestResult = ProviderTestResponse;
export type StoredProviderConfig = MaskedProvider;
