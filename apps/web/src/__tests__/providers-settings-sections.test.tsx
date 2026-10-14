// @vitest-environment jsdom
/** Settings lists providers by role, working ones first, and leaves Composio to Integrations setup. */

import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";

/** Catalog display order, each provider with the label the catalog serves for it. */
const CATALOG_LABELS: [string, string][] = [
  ["openrouter", "OpenRouter"],
  ["gemini", "Google Gemini"],
  ["ollama", "Ollama"],
  ["custom", "Custom"],
  ["tavily", "Tavily"],
  ["composio", "Composio"],
  ["e2b", "E2B Sandbox"],
  ["openai", "OpenAI"],
  ["resend", "Resend Email"],
  ["cloudinary", "Cloudinary"],
  ["google_oauth", "Google OAuth"],
  ["firecrawl", "Firecrawl"],
];
const CATALOG_ORDER = CATALOG_LABELS.map(([key]) => key);

const catalog: ProviderCatalog = {
  llm_provider_keys: ["openrouter", "gemini", "openai", "ollama", "custom"],
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
        needs_base_url: false,
      },
    ]),
  ),
  custom_presets: {},
};

const configured = new Set(["openai", "firecrawl"]);

let status: SetupStatus;

const BASE_STATUS = {
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
  providers: Object.fromEntries(
    CATALOG_ORDER.map((key) => [
      key,
      {
        configured: configured.has(key),
        env_shadowed: false,
        source: configured.has(key) ? "env" : "unset",
      },
    ]),
  ),
  plans_seeded: false,
} as SetupStatus;

vi.mock("@/features/settings/hooks/useProviderCatalog", () => ({
  useProviderCatalog: () => ({ data: catalog, isError: false }),
}));
vi.mock("@/features/settings/hooks/useProviderConfigs", () => ({
  useProviderConfigs: () => ({
    data: {},
    isLoading: false,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/features/settings/hooks/useSetupStatus", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/settings/hooks/useSetupStatus")
  >()),
  useSetupStatus: () => ({ data: status, refetch: vi.fn() }),
}));

import { ProvidersSettings } from "@/features/settings/components/ProvidersSettings";

const section = (title: string) =>
  within(screen.getByRole("region", { name: title }));

const ROW_LABEL =
  /^(OpenRouter|Google Gemini|OpenAI|Ollama|Custom|Tavily|Composio|E2B Sandbox|Resend Email|Cloudinary|Google OAuth|Firecrawl)$/;

const rowLabels = (title: string) =>
  section(title)
    .getAllByText(ROW_LABEL)
    .map((label) => label.textContent);

describe("ProvidersSettings", () => {
  beforeEach(() => {
    status = BASE_STATUS;
  });

  it("groups providers by role instead of one unlabelled list", () => {
    render(<ProvidersSettings />);

    expect(rowLabels("AI models")).toContain("OpenAI");
    expect(rowLabels("AI models")).not.toContain("Tavily");
    expect(rowLabels("Search & tools")).toEqual(
      expect.arrayContaining(["Tavily", "Firecrawl", "E2B Sandbox"]),
    );
    expect(rowLabels("Email")).toEqual(["Resend Email"]);
  });

  it("lists the working provider first within its section", () => {
    render(<ProvidersSettings />);

    expect(rowLabels("AI models")[0]).toBe("OpenAI");
    expect(rowLabels("Search & tools")[0]).toBe("Firecrawl");
  });

  it("sends Composio to Integrations setup instead of configuring it here", () => {
    render(<ProvidersSettings />);

    const integrations = section("Integrations");
    expect(rowLabels("Integrations")).toContain("Composio");
    expect(
      integrations
        .getByText("Open Integrations setup")
        .closest("a")
        ?.getAttribute("href"),
    ).toBe("/settings/integrations-setup");
    // Composio links out and Cloudinary isn't offered without its blob store.
    expect(screen.getAllByRole("button", { name: "Configure" })).toHaveLength(
      CATALOG_ORDER.length - 2,
    );
  });

  it("reports the local code sandbox on the E2B row when no E2B key is set", () => {
    status = {
      ...BASE_STATUS,
      deployment: { ...BASE_STATUS.deployment, local_code_sandbox: true },
    };
    render(<ProvidersSettings />);

    const tools = section("Search & tools");
    expect(tools.getByText("Local sandbox active")).toBeTruthy();
    // Only Tavily is left unconfigured: Firecrawl has a key, E2B runs locally.
    expect(tools.getAllByText("Not configured")).toHaveLength(1);
    expect(rowLabels("Search & tools").slice(0, 2)).toEqual(
      expect.arrayContaining(["E2B Sandbox", "Firecrawl"]),
    );
  });
});
