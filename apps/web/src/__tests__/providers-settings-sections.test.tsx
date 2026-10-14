// @vitest-environment jsdom
/** Settings lists providers by role, working ones first, and leaves Composio to Integrations setup. */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";

const CATALOG_ORDER = [
  "openrouter",
  "gemini",
  "ollama",
  "custom",
  "tavily",
  "composio",
  "e2b",
  "openai",
  "resend",
  "cloudinary",
  "google_oauth",
  "firecrawl",
];

const catalog: ProviderCatalog = {
  llm_provider_keys: ["openrouter", "gemini", "openai", "ollama", "custom"],
  providers: Object.fromEntries(
    CATALOG_ORDER.map((key) => [
      key,
      {
        label: key,
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

const status = {
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
  /^(OpenRouter|Google Gemini|OpenAI|Ollama|Custom Gateway|Tavily|Composio|E2B Sandbox|Resend Email|Cloudinary|Google OAuth|Firecrawl)$/;

const rowLabels = (title: string) =>
  section(title)
    .getAllByText(ROW_LABEL)
    .map((label) => label.textContent);

describe("ProvidersSettings", () => {
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
});
