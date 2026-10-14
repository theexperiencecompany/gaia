import type {
  CredentialProvider,
  ProviderCatalog,
} from "@/features/settings/api/providersApi";
import type { CustomPresetKey } from "@/features/setup-wizard/utils/providerCards";

interface ProviderRow {
  key: CredentialProvider;
  label: string;
  description: string;
  faviconDomain: string;
  needsBaseUrl: boolean;
  /** Tavily is a tool key — no model applies. */
  showModelField: boolean;
  /** Whether the backend can live-probe this credential (it cannot for Tavily). */
  connectionTestable: boolean;
}

/** A row's UI copy plus the endpoint defaults the catalog serves for it. */
export interface CatalogProviderRow extends ProviderRow {
  defaultBaseUrl: string;
  defaultModel: string;
}

// UI copy only — endpoint defaults and display order come from GET /setup/catalog.
const PROVIDER_ROWS: ProviderRow[] = [
  {
    key: "openrouter",
    label: "OpenRouter",
    description: "One key for every major model. Easiest way to start.",
    faviconDomain: "openrouter.ai",
    needsBaseUrl: false,
    showModelField: true,
    connectionTestable: true,
  },
  {
    key: "gemini",
    label: "Google Gemini",
    description: "Google's models, with a generous free tier.",
    faviconDomain: "ai.google.dev",
    needsBaseUrl: false,
    showModelField: true,
    connectionTestable: true,
  },
  {
    key: "openai",
    label: "OpenAI",
    description:
      "GPT models directly from OpenAI. Also powers voice-note transcription.",
    faviconDomain: "openai.com",
    needsBaseUrl: false,
    showModelField: true,
    connectionTestable: true,
  },
  {
    key: "ollama",
    label: "Ollama",
    description: "Run models locally — no API key needed.",
    faviconDomain: "ollama.com",
    needsBaseUrl: true,
    showModelField: true,
    connectionTestable: true,
  },
  {
    key: "custom",
    label: "Custom Gateway",
    description:
      "Any OpenAI-compatible endpoint — OpenCode Zen, Nous Research, or your own.",
    faviconDomain: "opencode.ai",
    needsBaseUrl: true,
    showModelField: true,
    connectionTestable: true,
  },
  {
    key: "tavily",
    label: "Tavily",
    description: "Web search results grounded in live sources.",
    faviconDomain: "tavily.com",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
  // Tool / integration keys below mirror the tavily card shape: a single
  // credential, no endpoint or model, and no live probe (the test endpoint
  // only knows LLM wires).
  {
    key: "composio",
    label: "Composio",
    description:
      "Integration platform for Gmail, Calendar, Slack, and 200+ tools.",
    faviconDomain: "composio.dev",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
  {
    key: "e2b",
    label: "E2B Sandbox",
    description: "Code execution sandbox for the agent's bash/code tools.",
    faviconDomain: "e2b.dev",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
  {
    key: "resend",
    label: "Resend Email",
    description: "Outbound email for notifications and reminders.",
    faviconDomain: "resend.com",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
  {
    key: "cloudinary",
    label: "Cloudinary",
    description:
      "Image upload and storage. Also needs CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_SECRET in .env — the key alone is not enough.",
    faviconDomain: "cloudinary.com",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
  {
    key: "google_oauth",
    label: "Google OAuth",
    description:
      "Google account integration (Gmail, Calendar). Also needs GOOGLE_CLIENT_ID in .env — the secret alone cannot connect anything.",
    faviconDomain: "accounts.google.com",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
  {
    key: "firecrawl",
    label: "Firecrawl",
    description: "Advanced web scraping and crawling.",
    faviconDomain: "firecrawl.dev",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
];

export type CustomPresetId = CustomPresetKey | "manual";

export function resolveProviderRow(
  key: CredentialProvider,
  catalog: ProviderCatalog,
): CatalogProviderRow {
  const row = PROVIDER_ROWS.find((r) => r.key === key);
  if (!row) throw new Error(`No settings copy for provider "${key}"`);
  const meta = catalog.providers[key];
  return {
    ...row,
    defaultBaseUrl: meta.base_url,
    defaultModel: meta.default_model,
  };
}
