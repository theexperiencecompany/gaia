/**
 * Wizard-local constants over the shared providers API contract
 * (`@/features/settings/api/providersApi` owns the wire types).
 */

import type { CredentialProvider } from "@/features/settings/api/providersApi";

/** All credential-backed providers, in display order. */
export const SETUP_PROVIDER_KEYS = [
  "openrouter",
  "gemini",
  "ollama",
  "custom",
  "tavily",
] as const satisfies readonly CredentialProvider[];
