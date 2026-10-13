/**
 * Static UI copy for the setup wizard: step text and provider card configs.
 * Endpoint defaults (base URL, model) and the Custom card's preset gateways
 * come from GET /setup/catalog (see utils/providerCards), never from here.
 */

import type { Transition } from "motion/react";
import type { CredentialProvider } from "@/lib/api/setupTransport";

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
  showApiKey: boolean;
  showBaseUrl: boolean;
  showModel: boolean;
  /**
   * Whether the backend can live-probe this credential. Tavily is a search
   * tool key with no listable endpoint — the test endpoint hard-rejects it —
   * so its card saves directly and reports "Saved" instead of "Connected".
   */
  connectionTestable: boolean;
  /** Offers the catalog's OpenAI-compatible preset gateways as chips. */
  hasPresets: boolean;
}

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
    hasPresets: false,
  },
  {
    key: "openai",
    label: "OpenAI",
    description:
      "GPT models directly from OpenAI. Also powers voice-note transcription.",
    faviconDomain: "openai.com",
    showApiKey: true,
    showBaseUrl: false,
    showModel: false,
    connectionTestable: true,
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
    hasPresets: false,
  },
  {
    key: "custom",
    label: "Custom",
    description:
      "Use any service with an OpenAI-style API — like OpenCode or Nous — or enter your own server address.",
    faviconDomain: "opencode.ai",
    showApiKey: true,
    showBaseUrl: true,
    showModel: true,
    connectionTestable: true,
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
  hasPresets: false,
};

/**
 * Tool / integration keys the wizard offers — a single credential each, no
 * endpoint or model. google_oauth and cloudinary are deliberately absent: a
 * pasted key alone cannot make them work (Google also needs its client id,
 * Cloudinary its cloud name + secret, all env-only), so offering them here
 * would report "Connected" for a dead integration. They stay configurable in
 * Settings, where the cards say what else they need.
 */
export const WIZARD_EXCLUDED_TOOL_KEYS = [
  "google_oauth",
  "cloudinary",
] as const;
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
