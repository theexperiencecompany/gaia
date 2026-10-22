// @vitest-environment jsdom
/** The provider step is the same one-picker form as Settings: what serves chat now, then one provider's fields. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";

vi.mock("@/features/settings/api/providersApi", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/settings/api/providersApi")
  >()),
  providersApi: { testProvider: vi.fn(), upsertProvider: vi.fn() },
}));
vi.mock("@/components/shared/ConfirmationDialog", () => ({
  ConfirmationDialog: () => null,
}));
vi.mock("@/features/settings/hooks/useProviderConfigs", () => ({
  useProviderConfigs: () => ({ data: {}, isLoading: false, refetch: vi.fn() }),
}));

import { ProviderStep } from "@/features/setup-wizard/components/steps/ProviderStep";

/** Chat providers in catalog order, each with the label the catalog serves for it. */
const LLM_LABELS: [string, string][] = [
  ["openrouter", "OpenRouter"],
  ["gemini", "Google Gemini"],
  ["openai", "OpenAI"],
  ["ollama", "Ollama"],
  ["custom", "Custom"],
];
const LLM_KEYS = LLM_LABELS.map(([key]) => key);

const CATALOG: ProviderCatalog = {
  llm_provider_keys: LLM_KEYS,
  providers: Object.fromEntries(
    LLM_LABELS.map(([key, label]) => [
      key,
      {
        label,
        description: null,
        key_url: null,
        base_url: null,
        default_model: null,
        favicon_url: `https://${key}.example/favicon.ico`,
        needs_base_url: false,
        account_id_label: null,
        second_key_label: null,
        api_key_label: "API key",
        takes_key: true,
        takes_model: true,
        managed_at: null,
      },
    ]),
  ),
  custom_presets: {},
  features: {
    ai_models: {
      label: "AI models",
      description: "",
      built_in: null,
      providers: LLM_KEYS,
    },
  },
} as ProviderCatalog;

const unset = { configured: false, env_shadowed: false, source: "unset" };

function statusWith(
  providers: SetupStatus["providers"] = {},
  inUse: string[] = [],
): SetupStatus {
  return {
    auth_mode: "local",
    has_admin_account: true,
    registration_policy: "invite_only",
    needs_setup: false,
    wizard_dismissed: false,
    deployment: {
      kind: "selfhost",
      bills: false,
      local_code_sandbox: false,
      blob_store: "local",
      gaia_support: false,
      instance_toolkits: true,
      private_network_endpoints: true,
    },
    providers: {
      ...Object.fromEntries(LLM_KEYS.map((key) => [key, unset])),
      ...providers,
    },
    features: {
      ai_models: { working: inUse.length > 0, available: true, in_use: inUse },
    },
    plans_seeded: false,
    bots: {
      telegram_username: null,
      discord_client_id: null,
      slack_workspace_url: null,
    },
  } as SetupStatus;
}

const renderStep = (status: SetupStatus) =>
  render(<ProviderStep status={status} catalog={CATALOG} onSaved={vi.fn()} />);

describe("ProviderStep on a fresh instance", () => {
  it("offers one provider picker with only OpenRouter's fields, not a card per provider", () => {
    renderStep(statusWith());

    expect(screen.getByText("Not set up yet")).toBeTruthy();
    expect(screen.getAllByLabelText("API key")).toHaveLength(1);
    expect(
      screen.getByPlaceholderText("Paste your OpenRouter key"),
    ).toBeTruthy();
    expect(screen.queryByPlaceholderText("Paste your OpenAI key")).toBeNull();
  });
});

describe("ProviderStep on an instance that already has a provider", () => {
  it("opens on the provider serving chat, marked in use", () => {
    renderStep(
      statusWith(
        { openai: { configured: true, env_shadowed: false, source: "env" } },
        ["openai"],
      ),
    );

    expect(screen.getByText("Using: OpenAI")).toBeTruthy();
    expect(screen.getByText("In use")).toBeTruthy();
    expect(screen.getByPlaceholderText("Paste your OpenAI key")).toBeTruthy();
    expect(
      screen.queryByPlaceholderText("Paste your OpenRouter key"),
    ).toBeNull();
  });
});
