// @vitest-environment jsdom
/** Settings lists each feature as one row with its status; a row opens to what it runs on and one picker over its providers. */

import type { FeatureSpec, FeatureStatus } from "@gaia/shared/api/generated";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
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
        description: null,
        key_url: null,
        base_url: null,
        default_model: null,
        favicon_url: `https://${key}.example/favicon.ico`,
        needs_base_url: key === "searxng",
        account_id_label: key === "cloudinary" ? "Cloud name" : null,
        second_key_label: key === "cloudinary" ? "API secret" : null,
        api_key_label: "API key",
        takes_key: key !== "searxng",
        takes_model: key === "openrouter" || key === "openai",
        managed_at:
          key === "composio"
            ? {
                href: "/settings/integrations-setup",
                label: "Open Integrations setup",
              }
            : null,
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

/** A row's trigger: its name is the feature, then its status and summary. */
const withQueryClient = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>
    {children}
  </QueryClientProvider>
);

const trigger = (title: string) =>
  screen.getByRole("button", { name: new RegExp(`^${title}`) });

/** A feature's row, collapsed or open. */
const row = (title: string) => {
  const item = trigger(title).closest<HTMLElement>('[data-slot="base"]');
  if (!item) throw new Error(`No row for ${title}`);
  return within(item);
};

/** Open a feature's row and return it. */
const open = (title: string) => {
  fireEvent.click(trigger(title));
  return row(title);
};

describe("ProvidersSettings", () => {
  beforeEach(() => {
    statusQuery.data = status;
    storedConfigs.data = {};
    searchParams.value = new URLSearchParams();
    render(<ProvidersSettings />, { wrapper: withQueryClient });
  });

  it("lists one row per feature, in catalog order, all closed", () => {
    expect(
      screen
        .getAllByRole("button", { expanded: false })
        .map((b) => b.querySelector(".font-medium")?.textContent),
    ).toEqual([
      "AI models",
      "Web search",
      "Reading web pages",
      "File storage",
      "Email",
      "Integrations",
      "Voice",
    ]);
    expect(screen.queryByLabelText("API key")).toBeNull();
  });

  it("tells your apps apart from tool keys, pointing at Integrations", () => {
    expect(
      screen.getByText("Integrations", { selector: "a" }).getAttribute("href"),
    ).toBe("/integrations");
  });

  it("says each feature's state on its closed row", () => {
    expect(row("Web search").getByText("Working")).toBeTruthy();
    expect(row("Web search").getByText("DuckDuckGo, free")).toBeTruthy();
    expect(row("AI models").getByText("OpenAI")).toBeTruthy();
    expect(row("Email").getByText("Not set up")).toBeTruthy();
    expect(row("Voice").getByText("Not available here")).toBeTruthy();
  });

  it("keeps keyless web search's providers behind an optional upgrade", () => {
    const search = open("Web search");
    expect(search.getByText("Already working with DuckDuckGo")).toBeTruthy();
    expect(search.queryByLabelText("API key")).toBeNull();

    fireEvent.click(search.getByRole("button", { name: /better provider/ }));

    expect(search.getAllByLabelText("API key")).toHaveLength(1);
    expect(search.getByPlaceholderText("Paste your Tavily key")).toBeTruthy();
    expect(search.queryByPlaceholderText("Paste your Exa key")).toBeNull();
  });

  it("picks the provider serving a feature and marks it in use", () => {
    const models = open("AI models");
    expect(models.getByText("Using: OpenAI")).toBeTruthy();
    expect(models.getByPlaceholderText("Paste your OpenAI key")).toBeTruthy();
    expect(
      models.queryByPlaceholderText("Paste your OpenRouter key"),
    ).toBeNull();
  });

  it("shows the picker, not the upgrade prompt, once a provider key is saved", () => {
    const reading = open("Reading web pages");
    expect(reading.getByText("Using: Built-in reader")).toBeTruthy();
    expect(reading.getByText("Backup: Firecrawl")).toBeTruthy();
    expect(reading.getByText("Connected")).toBeTruthy();
    expect(reading.queryByText(/better provider/)).toBeNull();
  });

  it("asks for a provider on a feature with no built-in and no key", () => {
    const email = open("Email");
    expect(email.getByText("Not set up yet")).toBeTruthy();
    expect(
      email.getByText("Pick a provider below to turn it on."),
    ).toBeTruthy();
  });

  it("explains a feature this instance cannot run, with a docs link and no key field", () => {
    const voice = open("Voice");
    expect(
      voice.getAllByText("Voice needs GAIA Cloud's LiveKit project."),
    ).not.toEqual([]);
    expect(
      voice.getByText("Read the docs").closest("a")?.getAttribute("href"),
    ).toBe("https://docs.example/voice");
    expect(voice.queryByLabelText("API key")).toBeNull();
    expect(voice.queryByText(/Provider/)).toBeNull();
  });

  it("sends Composio to Integrations setup and hides Cloudinary on local storage", () => {
    expect(
      open("Integrations")
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
    const { rerender } = render(<ProvidersSettings />, {
      wrapper: withQueryClient,
    });

    statusQuery.data = status;
    rerender(<ProvidersSettings />);

    const models = open("AI models");
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
    render(<ProvidersSettings />, { wrapper: withQueryClient });

    const storage = open("File storage");
    fireEvent.click(storage.getByRole("button", { name: /better provider/ }));
    expect(
      (storage.getByLabelText("Cloud name") as HTMLInputElement).value,
    ).toBe("my-cloud");
    expect(
      storage.getByPlaceholderText("Stored (...abcd), paste to replace"),
    ).toBeTruthy();
    expect(open("Email").queryByLabelText("Cloud name")).toBeNull();
  });
});

describe("ProvidersSettings opened for one feature", () => {
  it("opens the linked feature's row and scrolls it into view", () => {
    statusQuery.data = status;
    searchParams.value = new URLSearchParams("feature=email");
    const scrolled: string[] = [];
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this.id);
    };
    render(<ProvidersSettings />, { wrapper: withQueryClient });

    expect(scrolled).toEqual(["provider-feature-email"]);
    expect(trigger("Email").getAttribute("aria-expanded")).toBe("true");
  });
});
