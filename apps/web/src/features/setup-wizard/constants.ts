/**
 * Static UI copy for the setup wizard: step text and provider card configs.
 * Provider copy, endpoint defaults and the Custom card's preset gateways come
 * from GET /setup/catalog (see utils/providerCards), never from here.
 */

import type { Transition } from "motion/react";
import type { CredentialProvider } from "@/features/settings/api/providersApi";

const EASE_OUT_QUART: [number, number, number, number] = [0.19, 1, 0.22, 1];

export const MOTION_FADE_UP = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.4, ease: EASE_OUT_QUART } satisfies Transition,
} as const;

/** How a card's form behaves; its copy comes from the provider catalog. */
export interface ProviderCardConfig {
  key: CredentialProvider;
  showApiKey: boolean;
  showModel: boolean;
  /** Offers the catalog's OpenAI-compatible preset gateways as chips. */
  hasPresets: boolean;
}

/** A single-credential card: no endpoint, model or preset gateways. */
const keyOnlyCard = (key: CredentialProvider): ProviderCardConfig => ({
  key,
  showApiKey: true,
  showModel: false,
  hasPresets: false,
});

export const LLM_PROVIDER_CARDS: ProviderCardConfig[] = [
  keyOnlyCard("openrouter"),
  keyOnlyCard("gemini"),
  keyOnlyCard("openai"),
  { key: "ollama", showApiKey: false, showModel: true, hasPresets: false },
  { key: "custom", showApiKey: true, showModel: true, hasPresets: true },
];

/**
 * Tool / integration keys the wizard offers. google_oauth and cloudinary are
 * deliberately absent: each needs a multi-part account (Google a client id and
 * secret, Cloudinary a cloud name, key and secret) that only optional setups
 * use, so first-run setup leaves them to their Settings cards.
 */
export const TOOL_PROVIDER_CARDS: ProviderCardConfig[] = [
  keyOnlyCard("composio"),
  keyOnlyCard("e2b"),
  keyOnlyCard("resend"),
  keyOnlyCard("firecrawl"),
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
    title: "Web search",
    subtitle:
      "Optional. Search works out of the box for free; pick a provider for better results.",
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
