/**
 * Static metadata for the setup wizard: step copy and provider card configs.
 * The OpenAI-compatible presets offered inside the Custom card live beside
 * the API contract in `@/features/settings/api/providersApi` (CUSTOM_PRESETS)
 * so the wizard and Settings render one shared catalog. The API remains the
 * source of truth for behavior; these only drive UI.
 */

import type { Transition } from "motion/react";
import {
  type CredentialProvider,
  CUSTOM_PRESETS,
} from "@/features/settings/api/providersApi";

const EASE_OUT_QUART: [number, number, number, number] = [0.19, 1, 0.22, 1];

export const MOTION_FADE_UP = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.4, ease: EASE_OUT_QUART } satisfies Transition,
} as const;

/** Brand favicon for a provider card lives on the providers API
 * (`providerFaviconUrl`) so wizard and settings share one source. */

export interface ProviderCardConfig {
  key: CredentialProvider;
  label: string;
  description: string;
  faviconDomain: string;
  /** Favicon swaps with the selected preset (Custom card only). */
  presetFavicon?: Record<string, string>;
  showApiKey: boolean;
  showBaseUrl: boolean;
  showModel: boolean;
  /**
   * Whether the backend can live-probe this credential. Tavily is a search
   * tool key with no listable endpoint — the test endpoint hard-rejects it —
   * so its card saves directly and reports "Saved" instead of "Connected".
   */
  connectionTestable: boolean;
  defaultBaseUrl: string;
  defaultModel: string;
  hasPresets: boolean;
}

/**
 * One-click Ollama defaults — the local endpoint + model the wizard's
 * "Use local Ollama" shortcut saves without a probe. Kept here so the card
 * defaults and the shortcut stay in sync; the backend allows this private
 * address for ollama (see setup.py `_assert_url_safe`).
 */
export const OLLAMA_ONE_CLICK = {
  baseUrl: "http://host.docker.internal:11434",
  model: "llama3.2",
} as const;

export const LLM_PROVIDER_CARDS: ProviderCardConfig[] = [
  {
    key: "openrouter",
    label: "OpenRouter",
    description: "One key for every major model. Easiest way to start.",
    faviconDomain: "openrouter.ai",
    showApiKey: true,
    showBaseUrl: false,
    showModel: false,
    connectionTestable: true,
    defaultBaseUrl: "",
    defaultModel: "",
    hasPresets: false,
  },
  {
    key: "gemini",
    label: "Google Gemini",
    description: "Google's models, with a generous free tier.",
    faviconDomain: "ai.google.dev",
    showApiKey: true,
    showBaseUrl: false,
    showModel: false,
    connectionTestable: true,
    defaultBaseUrl: "",
    defaultModel: "",
    hasPresets: false,
  },
  {
    key: "ollama",
    label: "Ollama",
    description: "Run models locally — no API key needed.",
    faviconDomain: "ollama.com",
    showApiKey: false,
    showBaseUrl: true,
    showModel: true,
    connectionTestable: true,
    defaultBaseUrl: OLLAMA_ONE_CLICK.baseUrl,
    defaultModel: OLLAMA_ONE_CLICK.model,
    hasPresets: false,
  },
  {
    key: "custom",
    label: "Custom / OpenAI-compatible",
    description:
      "Any OpenAI-compatible endpoint. Pick a preset or enter your own.",
    faviconDomain: "opencode.ai",
    presetFavicon: Object.fromEntries(
      CUSTOM_PRESETS.map((p) => [p.key, p.faviconDomain]),
    ),
    showApiKey: true,
    showBaseUrl: true,
    showModel: true,
    connectionTestable: true,
    defaultBaseUrl: "",
    defaultModel: "",
    hasPresets: true,
  },
];

export const SEARCH_PROVIDER_CARD: ProviderCardConfig = {
  key: "tavily",
  label: "Tavily",
  description: "Web search results grounded in live sources.",
  faviconDomain: "tavily.com",
  showApiKey: true,
  showBaseUrl: false,
  showModel: false,
  connectionTestable: false,
  defaultBaseUrl: "",
  defaultModel: "",
  hasPresets: false,
};

/**
 * Tool / integration keys configured like tavily — a single credential with
 * no endpoint or model. Not rendered by a wizard step today; exported so the
 * wizard and Settings share one catalog (mirrors the tail of
 * CREDENTIAL_PROVIDERS in app/constants/providers.py).
 */
export const TOOL_PROVIDER_CARDS: ProviderCardConfig[] = [
  {
    key: "composio",
    label: "Composio",
    description:
      "Integration platform for Gmail, Calendar, Slack, and 200+ tools.",
    faviconDomain: "composio.dev",
    showApiKey: true,
    showBaseUrl: false,
    showModel: false,
    connectionTestable: false,
    defaultBaseUrl: "",
    defaultModel: "",
    hasPresets: false,
  },
  {
    key: "e2b",
    label: "E2B Sandbox",
    description: "Code execution sandbox for the agent's bash/code tools.",
    faviconDomain: "e2b.dev",
    showApiKey: true,
    showBaseUrl: false,
    showModel: false,
    connectionTestable: false,
    defaultBaseUrl: "",
    defaultModel: "",
    hasPresets: false,
  },
  {
    key: "openai",
    label: "OpenAI",
    description: "Used for voice-note transcription (Whisper).",
    faviconDomain: "openai.com",
    showApiKey: true,
    showBaseUrl: false,
    showModel: false,
    connectionTestable: false,
    defaultBaseUrl: "",
    defaultModel: "",
    hasPresets: false,
  },
  {
    key: "resend",
    label: "Resend Email",
    description: "Outbound email for notifications and reminders.",
    faviconDomain: "resend.com",
    showApiKey: true,
    showBaseUrl: false,
    showModel: false,
    connectionTestable: false,
    defaultBaseUrl: "",
    defaultModel: "",
    hasPresets: false,
  },
  {
    key: "cloudinary",
    label: "Cloudinary",
    description: "Image upload and storage for chat media.",
    faviconDomain: "cloudinary.com",
    showApiKey: true,
    showBaseUrl: false,
    showModel: false,
    connectionTestable: false,
    defaultBaseUrl: "",
    defaultModel: "",
    hasPresets: false,
  },
  {
    key: "google_oauth",
    label: "Google OAuth",
    description: "Google account integration (Gmail, Calendar).",
    faviconDomain: "accounts.google.com",
    showApiKey: true,
    showBaseUrl: false,
    showModel: false,
    connectionTestable: false,
    defaultBaseUrl: "",
    defaultModel: "",
    hasPresets: false,
  },
  {
    key: "firecrawl",
    label: "Firecrawl",
    description: "Advanced web scraping and crawling.",
    faviconDomain: "firecrawl.dev",
    showApiKey: true,
    showBaseUrl: false,
    showModel: false,
    connectionTestable: false,
    defaultBaseUrl: "",
    defaultModel: "",
    hasPresets: false,
  },
];

export interface WizardStepMeta {
  id: "account" | "provider" | "search" | "integrations" | "done";
  title: string;
  subtitle: string;
}

/**
 * Optional first step: on a fresh local-auth instance no administrator exists
 * yet, and every provider write needs its session — so the wizard asks for
 * the admin account before anything else.
 */
export const ACCOUNT_STEP: WizardStepMeta = {
  id: "account",
  title: "Create your admin account",
  subtitle:
    "This instance needs an administrator before it can be configured. It takes one email and password — you'll continue straight into setup.",
};

export const WIZARD_STEPS: WizardStepMeta[] = [
  {
    id: "provider",
    title: "Choose an AI provider",
    subtitle:
      "GAIA needs one provider to think with. Paste an API key or point at your own endpoint — you can change this anytime in Settings.",
  },
  {
    id: "search",
    title: "Add web search",
    subtitle:
      "Optional. A Tavily key lets GAIA search the web for up-to-date information when answering.",
  },
  {
    id: "integrations",
    title: "Connect your accounts",
    subtitle:
      "Optional. Link the tools you already use so GAIA can work with them directly.",
  },
  {
    id: "done",
    title: "You're all set",
    subtitle: "Here's what your instance has configured so far.",
  },
];
