/**
 * Static UI copy for the setup wizard: step text and which features it offers.
 * Provider copy, endpoint defaults and preset gateways come from
 * GET /setup/catalog, never from here.
 */

import type { ProviderFeature } from "@gaia/shared/api/generated";

/** The tool features the wizard's accounts step offers keys for; the rest stay in Settings. */
export const WIZARD_TOOL_FEATURES: readonly ProviderFeature[] = [
  "email",
  "code_running",
  "page_reading",
];

export interface WizardStepMeta {
  id: "account" | "provider" | "search" | "integrations" | "done";
  title: string;
  subtitle: string;
  /** Marked Optional in the heading; Continue never waits on it. */
  optional: boolean;
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
  optional: false,
};

export const WIZARD_STEPS: WizardStepMeta[] = [
  {
    id: "provider",
    title: "Choose an AI provider",
    subtitle:
      "GAIA needs one provider to think with. Pick one and paste its key — you can change it anytime in Settings.",
    optional: false,
  },
  {
    id: "search",
    title: "Web search",
    subtitle:
      "Search already works for free. Add a provider only if you want better results.",
    optional: true,
  },
  {
    id: "integrations",
    title: "Connect your accounts",
    subtitle:
      "Sign into the apps you use so GAIA can work in them. Everything here can wait until later.",
    optional: true,
  },
  {
    id: "done",
    title: "You're all set",
    subtitle: "Here's what your instance has configured so far.",
    optional: false,
  },
];
