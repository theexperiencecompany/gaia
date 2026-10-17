// @vitest-environment jsdom
/** Settings shows one card per feature: whether it works, what it runs on, and one picker over its providers. */

import type { FeatureSpec, FeatureStatus } from "@gaia/shared/api/generated";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  ProviderCatalog,
  SetupStatus,
  StoredProviderConfig,
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
        account_id_label: key === "cloudinary" ? "Cloud name" : "",
        second_key_label: key === "cloudinary" ? "API secret" : "",
        api_key_label: "API key",
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
    voice: {
      ...feature("Voice", [], {
        engine: "hosted_voice",
        label: "GAIA voice",
        description: "Hosted voice.",
      }),
      self_host_gap: {
        reason: "Voice needs GAIA Cloud's LiveKit project.",
        docs_url: "https://docs.example/voice",
      },
    },
  },
};

const configured = new Set(["openai", "firecrawl"]);

const using = (...in_use: FeatureStatus["in_use"]): FeatureStatus => ({
  working: in_use.length > 0,
  available: true,
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
    voice: { working: false, available: false, in_use: [] },
  },
  plans_seeded: false,
  bots: {
    telegram_username: null,
    discord_client_id: null,
    slack_workspace_url: null,
  },
} as SetupStatus;

const statusQuery: { data: SetupStatus | undefined } = { data: status };
const storedConfigs: { data: Record<string, StoredProviderConfig> } = {
  data: {},
};

const searchParams = { value: new URLSearchParams() };

vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParams.value,
}));
vi.mock("@/components/shared/ConfirmationDialog", () => ({
  ConfirmationDialog: () => null,
}));
vi.mock("@/features/settings/hooks/useProviderCatalog", () => ({
  useProviderCatalog: () => ({ data: catalog, isError: false }),
}));
vi.mock("@/features/settings/hooks/useProviderConfigs", () => ({
  useProviderConfigs: () => ({
    data: storedConfigs.data,
    isLoading: false,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/features/settings/hooks/useSetupStatus", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/settings/hooks/useSetupStatus")
  >()),
  useSetupStatus: () => ({ data: statusQuery.data, refetch: vi.fn() }),
}));

import { ProvidersSettings } from "@/features/settings/components/ProvidersSettings";

const card = (title: string) =>
  within(screen.getByRole("region", { name: title }));

describe("ProvidersSettings", () => {
  beforeEach(() => {
    statusQuery.data = status;
    storedConfigs.data = {};
    searchParams.value = new URLSearchParams();
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
      "Voice",
    ]);
  });

  it("shows keyless web search working, with one picker and only the picked provider's key", () => {
    const search = card("Web search");
    expect(search.getByText("Working")).toBeTruthy();
    expect(search.getByText("Using: DuckDuckGo")).toBeTruthy();
    expect(search.getByText("Free, no key needed.")).toBeTruthy();
    expect(search.getAllByLabelText("Provider", { exact: false })).not.toEqual(
      [],
    );
    expect(search.getAllByLabelText("API key")).toHaveLength(1);
    expect(search.getByPlaceholderText("Paste your Tavily key")).toBeTruthy();
    expect(search.queryByPlaceholderText("Paste your Exa key")).toBeNull();
  });

  it("picks the provider serving a feature and marks it in use", () => {
    const models = card("AI models");
    expect(models.getByText("Using: OpenAI")).toBeTruthy();
    expect(models.getByPlaceholderText("Paste your OpenAI key")).toBeTruthy();
    expect(
      models.queryByPlaceholderText("Paste your OpenRouter key"),
    ).toBeNull();
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
    expect(
      email.getByText("Pick a provider below to turn it on."),
    ).toBeTruthy();
  });

  it("explains a feature this instance cannot run, with a docs link and no key field", () => {
    const voice = card("Voice");
    expect(voice.getByText("Unavailable")).toBeTruthy();
    expect(
      voice.getByText("Voice needs GAIA Cloud's LiveKit project."),
    ).toBeTruthy();
    expect(
      voice.getByText("Read the docs").closest("a")?.getAttribute("href"),
    ).toBe("https://docs.example/voice");
    expect(voice.queryByLabelText("API key")).toBeNull();
    expect(voice.queryByText(/Provider/)).toBeNull();
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

describe("ProvidersSettings before setup status loads", () => {
  it("picks the serving provider once status arrives after the first render", () => {
    statusQuery.data = undefined;
    const { rerender } = render(<ProvidersSettings />);

    statusQuery.data = status;
    rerender(<ProvidersSettings />);

    const models = card("AI models");
    expect(models.getByPlaceholderText("Paste your OpenAI key")).toBeTruthy();
  });
});

describe("ProvidersSettings for a two-part account", () => {
  it("asks for Cloudinary's cloud name and API secret, seeding what is stored", () => {
    statusQuery.data = {
      ...status,
      deployment: { ...status.deployment, blob_store: "cloudinary" },
    };
    storedConfigs.data = {
      cloudinary: {
        configured: true,
        account_id: "my-cloud",
        api_key_hint: "...1234",
        api_secret_hint: "...abcd",
      } as StoredProviderConfig,
    };
    render(<ProvidersSettings />);

    const storage = card("File storage");
    expect(
      (storage.getByLabelText("Cloud name") as HTMLInputElement).value,
    ).toBe("my-cloud");
    expect(
      storage.getByPlaceholderText("Stored (...abcd), paste to replace"),
    ).toBeTruthy();
    expect(card("Email").queryByLabelText("Cloud name")).toBeNull();
  });
});

describe("ProvidersSettings opened for one feature", () => {
  it("scrolls the linked feature's card into view", () => {
    statusQuery.data = status;
    searchParams.value = new URLSearchParams("feature=email");
    const scrolled: string[] = [];
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this.querySelector("section")?.ariaLabel ?? "");
    };
    render(<ProvidersSettings />);

    expect(scrolled).toEqual(["Email"]);
  });
});
