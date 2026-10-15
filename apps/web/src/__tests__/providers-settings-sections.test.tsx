// @vitest-environment jsdom
/** Settings shows one card per feature: whether it works, what it runs on, and its optional providers. */

import type { FeatureSpec, FeatureStatus } from "@gaia/shared/api/generated";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";

const CATALOG_LABELS: [string, string][] = [
  ["openrouter", "OpenRouter"],
  ["openai", "OpenAI"],
  ["tavily", "Tavily"],
  ["exa", "Exa"],
  ["searxng", "SearXNG"],
  ["firecrawl", "Firecrawl"],
  ["resend", "Resend Email"],
  ["composio", "Composio"],
  ["cloudinary", "Cloudinary"],
];

const feature = (
  label: string,
  providers: FeatureSpec["providers"],
  builtIn: FeatureSpec["built_in"] = null,
): FeatureSpec => ({ label, description: "", built_in: builtIn, providers });

const catalog: ProviderCatalog = {
  llm_provider_keys: ["openrouter", "openai"],
  providers: Object.fromEntries(
    CATALOG_LABELS.map(([key, label]) => [
      key,
      {
        label,
        description: "",
        key_url: "",
        base_url: "",
        default_model: "",
        favicon_domain: `${key}.example`,
        needs_base_url: key === "searxng",
      },
    ]),
  ),
  custom_presets: {},
  features: {
    ai_models: feature("AI models", ["openrouter", "openai"]),
    web_search: feature("Web search", ["tavily", "exa", "searxng"], {
      engine: "duckduckgo",
      label: "DuckDuckGo",
      description: "Free, no key needed.",
    }),
    page_reading: feature("Reading web pages", ["firecrawl"], {
      engine: "page_reader",
      label: "Built-in reader",
      description: "No key needed.",
    }),
    file_storage: feature("File storage", ["cloudinary"], {
      engine: "local_disk",
      label: "This server's disk",
      description: "Files stay on your machine.",
    }),
    email: feature("Email", ["resend"]),
    integrations: feature("Integrations", ["composio"]),
  },
};

const configured = new Set(["openai", "firecrawl"]);

const using = (...in_use: FeatureStatus["in_use"]): FeatureStatus => ({
  working: in_use.length > 0,
  in_use,
});

const status = {
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
  providers: Object.fromEntries(
    CATALOG_LABELS.map(([key]) => [
      key,
      {
        configured: configured.has(key),
        env_shadowed: false,
        source: configured.has(key) ? "env" : "unset",
      },
    ]),
  ),
  features: {
    ai_models: using("openai"),
    web_search: using("duckduckgo"),
    page_reading: using("page_reader", "firecrawl"),
    file_storage: using("local_disk"),
    email: using(),
    integrations: using(),
  },
  plans_seeded: false,
  bots: {
    telegram_username: null,
    discord_client_id: null,
    slack_workspace_url: null,
  },
} as SetupStatus;

vi.mock("@/features/settings/hooks/useProviderCatalog", () => ({
  useProviderCatalog: () => ({ data: catalog, isError: false }),
}));
vi.mock("@/features/settings/hooks/useProviderConfigs", () => ({
  useProviderConfigs: () => ({ data: {}, isLoading: false, refetch: vi.fn() }),
}));
vi.mock("@/features/settings/hooks/useSetupStatus", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/settings/hooks/useSetupStatus")
  >()),
  useSetupStatus: () => ({ data: status, refetch: vi.fn() }),
}));

import { ProvidersSettings } from "@/features/settings/components/ProvidersSettings";

const card = (title: string) =>
  within(screen.getByRole("region", { name: title }));

describe("ProvidersSettings", () => {
  beforeEach(() => {
    render(<ProvidersSettings />);
  });

  it("renders one card per feature, in catalog order", () => {
    expect(screen.getAllByRole("region").map((r) => r.ariaLabel)).toEqual([
      "AI models",
      "Web search",
      "Reading web pages",
      "File storage",
      "Email",
      "Integrations",
    ]);
  });

  it("shows keyless web search working, with its keys as optional upgrades", () => {
    const search = card("Web search");
    expect(search.getByText("Working")).toBeTruthy();
    expect(search.getByText("Using: DuckDuckGo")).toBeTruthy();
    expect(search.getByText("Optional upgrades")).toBeTruthy();
    expect(search.getAllByRole("button", { name: "Add key" })).toHaveLength(2);
    expect(search.getByRole("button", { name: "Add address" })).toBeTruthy();
  });

  it("names the engine in use first and the rest as backups", () => {
    const reading = card("Reading web pages");
    expect(reading.getByText("Using: Built-in reader")).toBeTruthy();
    expect(reading.getByText("Backup: Firecrawl")).toBeTruthy();
    expect(reading.getByText("Connected")).toBeTruthy();
  });

  it("marks a feature with no built-in and no key as off", () => {
    const email = card("Email");
    expect(email.getByText("Off")).toBeTruthy();
    expect(email.getByText("Not running")).toBeTruthy();
    expect(email.getByText("Add a provider below to turn it on.")).toBeTruthy();
  });

  it("sends Composio to Integrations setup and hides Cloudinary on local storage", () => {
    expect(
      card("Integrations")
        .getByText("Open Integrations setup")
        .closest("a")
        ?.getAttribute("href"),
    ).toBe("/settings/integrations-setup");
    expect(screen.queryByText("Cloudinary")).toBeNull();
  });
});
