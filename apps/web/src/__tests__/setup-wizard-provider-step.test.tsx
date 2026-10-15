// @vitest-environment jsdom
/** The provider step opens on what the instance already runs, never on an empty OpenRouter card. */

import { fireEvent, render, screen } from "@testing-library/react";
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
        description: "",
        key_url: "",
        base_url: "",
        default_model: "",
        favicon_domain: `${key}.example`,
        needs_base_url: false,
        account_id_label: "",
        second_key_label: "",
      },
    ]),
  ),
  custom_presets: {},
  features: {},
};

const unset = { configured: false, env_shadowed: false, source: "unset" };

function statusWith(providers: SetupStatus["providers"] = {}): SetupStatus {
  return {
    auth_mode: "local",
    has_admin_account: true,
    registration_policy: "invite_only",
    needs_setup: false,
    deployment: {
      kind: "selfhost",
      bills: false,
      local_code_sandbox: false,
      blob_store: "local",
      gaia_support: false,
    },
    providers: {
      ...Object.fromEntries(LLM_KEYS.map((key) => [key, unset])),
      ...providers,
    },
    features: {},
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

describe("ProviderStep on an instance that already has a provider", () => {
  const openaiFromEnv = statusWith({
    openai: { configured: true, env_shadowed: false, source: "env" },
  });

  it("says which provider is connected and where it comes from", () => {
    renderStep(openaiFromEnv);

    expect(screen.getByText("OpenAI is connected")).toBeTruthy();
    expect(screen.getByText(/from the server's configuration/i)).toBeTruthy();
    expect(screen.queryByPlaceholderText("Paste your API key")).toBeNull();
  });

  it("offers the configured provider first when changing, not OpenRouter", () => {
    renderStep(openaiFromEnv);

    fireEvent.click(screen.getByRole("button", { name: "Change provider" }));

    expect(screen.getByText("OpenAI")).toBeTruthy();
    expect(screen.queryByText("OpenRouter")).toBeNull();
  });

  it("names a key saved on this instance as saved, not as server configuration", () => {
    renderStep(
      statusWith({
        gemini: { configured: true, env_shadowed: false, source: "stored" },
      }),
    );

    expect(screen.getByText("Google Gemini is connected")).toBeTruthy();
    expect(screen.queryByText(/from the server's configuration/i)).toBeNull();
  });
});

describe("ProviderStep on a fresh instance", () => {
  it("leads with OpenRouter's key field", () => {
    renderStep(statusWith());

    expect(screen.getByText("OpenRouter")).toBeTruthy();
    expect(screen.getByPlaceholderText("Paste your API key")).toBeTruthy();
    expect(screen.queryByText(/is connected/)).toBeNull();
  });
});

describe("ProviderStep lanes on a fresh instance", () => {
  it("keeps the other hosted providers behind More providers, OpenRouter first", () => {
    renderStep(statusWith());

    expect(screen.queryByText("Google Gemini")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "More providers" }));

    const labels = ["OpenRouter", "Google Gemini", "OpenAI", "Custom"];
    const positions = labels.map((label) =>
      document.body.innerHTML.indexOf(`>${label}<`),
    );
    expect(positions.every((p) => p >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
    expect(screen.queryByText("Ollama")).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: "Show fewer providers" }),
    );
    expect(screen.queryByText("Google Gemini")).toBeNull();
  });

  it("shows only the Ollama card on the local tab", () => {
    renderStep(statusWith());

    fireEvent.click(
      screen.getByRole("button", { name: "Local Ollama · free" }),
    );

    expect(screen.getByText("Ollama")).toBeTruthy();
    expect(screen.queryByText("OpenRouter")).toBeNull();
  });

  it("continues without a provider from the skip tab", () => {
    const onNext = vi.fn();
    render(
      <ProviderStep
        status={statusWith()}
        catalog={CATALOG}
        onSaved={vi.fn()}
        onNext={onNext}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Skip for now" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Continue without a provider" }),
    );

    expect(onNext).toHaveBeenCalledOnce();
  });
});
