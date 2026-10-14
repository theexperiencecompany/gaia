import type {
  CredentialProvider,
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import {
  isProviderConfigured,
  runsCodeInLocalSandbox,
} from "@/features/settings/hooks/useSetupStatus";
import {
  type CatalogProvider,
  resolveCatalogProvider,
} from "@/features/settings/utils/providerCatalog";
import type { CustomPresetKey } from "@/features/setup-wizard/utils/providerCards";

/** The role a provider plays — Settings lists each role as its own section. */
const PROVIDER_SECTIONS = [
  {
    key: "models",
    title: "AI models",
    description: "The models GAIA chats and reasons with.",
  },
  {
    key: "tools",
    title: "Search & tools",
    description: "Web search, scraping and code execution for the agent.",
  },
  {
    key: "email",
    title: "Email",
    description: "How GAIA sends notifications and reminders.",
  },
  {
    key: "storage",
    title: "File storage",
    description: "Where uploaded and generated files are kept.",
  },
  {
    key: "integrations",
    title: "Integrations",
    description: "Connections to your accounts and apps.",
  },
] as const;

type ProviderSectionKey = (typeof PROVIDER_SECTIONS)[number]["key"];

interface ProviderRow {
  key: CredentialProvider;
  section: ProviderSectionKey;
  /** Tavily is a tool key — no model applies. */
  showModelField: boolean;
  /** The settings page that owns this credential, when it is not configured here. */
  managedAt?: { href: string; label: string };
}

/** A row's layout resolved against the catalog, which carries its copy and endpoint defaults. */
export type CatalogProviderRow = CatalogProvider & ProviderRow;

const llmRow = (key: CredentialProvider): ProviderRow => ({
  key,
  section: "models",
  showModelField: true,
});

const keyOnlyRow = (
  key: CredentialProvider,
  section: ProviderSectionKey,
): ProviderRow => ({ key, section, showModelField: false });

// Layout only — copy, endpoint defaults and display order come from GET /setup/catalog.
const PROVIDER_ROWS: ProviderRow[] = [
  llmRow("openrouter"),
  llmRow("gemini"),
  llmRow("openai"),
  llmRow("ollama"),
  llmRow("custom"),
  keyOnlyRow("tavily", "tools"),
  {
    ...keyOnlyRow("composio", "integrations"),
    managedAt: {
      href: "/settings/integrations-setup",
      label: "Open Integrations setup",
    },
  },
  keyOnlyRow("e2b", "tools"),
  keyOnlyRow("resend", "email"),
  keyOnlyRow("cloudinary", "storage"),
  keyOnlyRow("google_oauth", "integrations"),
  keyOnlyRow("firecrawl", "tools"),
];

export type CustomPresetId = CustomPresetKey | "manual";

export function resolveProviderRow(
  key: CredentialProvider,
  catalog: ProviderCatalog,
): CatalogProviderRow {
  const row = PROVIDER_ROWS.find((r) => r.key === key);
  if (!row) throw new Error(`No settings row for provider "${key}"`);
  return { ...resolveCatalogProvider(key, catalog), ...row };
}

/** What a row's status badge reports. */
export type ProviderRowState = "connected" | "local_sandbox" | "not_configured";

/** A provider's state; E2B without a key still runs code in an opted-in local sandbox. */
export function providerRowState(
  status: SetupStatus | undefined,
  key: CredentialProvider,
): ProviderRowState {
  if (isProviderConfigured(status, key)) return "connected";
  if (key === "e2b" && runsCodeInLocalSandbox(status)) return "local_sandbox";
  return "not_configured";
}

interface ProviderSectionGroup {
  key: ProviderSectionKey;
  title: string;
  description: string;
  rows: CatalogProviderRow[];
}

/** Rows grouped into their sections (empty ones dropped), working providers first. */
export function groupProviderRows(
  rows: readonly CatalogProviderRow[],
  isWorking: (key: CredentialProvider) => boolean,
): ProviderSectionGroup[] {
  return PROVIDER_SECTIONS.map((section) => ({
    ...section,
    rows: rows
      .filter((row) => row.section === section.key)
      .toSorted((a, b) => Number(isWorking(b.key)) - Number(isWorking(a.key))),
  })).filter((section) => section.rows.length > 0);
}
