import type {
  FeatureSpec,
  FeatureStatus,
  ProviderFeature,
} from "@gaia/shared/api/generated";
import type {
  CredentialProvider,
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import {
  isProviderConfigured,
  isProviderOffered,
} from "@/features/settings/hooks/useSetupStatus";
import {
  type CatalogProvider,
  resolveCatalogProvider,
} from "@/features/settings/utils/providerCatalog";
import type { CustomPresetKey } from "@/features/setup-wizard/utils/providerCards";

interface ProviderRow {
  key: CredentialProvider;
  /** Only chat providers take a model. */
  showModelField: boolean;
  /** SearXNG is reached by its address alone and takes no key. */
  showApiKey: boolean;
  /** The settings page that owns this credential, when it is not configured here. */
  managedAt?: { href: string; label: string };
}

/** A row's layout resolved against the catalog, which carries its copy and endpoint defaults. */
export type CatalogProviderRow = CatalogProvider & ProviderRow;

const llmRow = (key: CredentialProvider): ProviderRow => ({
  key,
  showModelField: true,
  showApiKey: true,
});

const keyOnlyRow = (key: CredentialProvider): ProviderRow => ({
  key,
  showModelField: false,
  showApiKey: true,
});

// Layout only — copy, endpoint defaults, features and display order come from GET /setup/catalog.
const PROVIDER_ROWS: ProviderRow[] = [
  llmRow("openrouter"),
  llmRow("gemini"),
  llmRow("openai"),
  llmRow("ollama"),
  llmRow("custom"),
  keyOnlyRow("tavily"),
  keyOnlyRow("exa"),
  keyOnlyRow("brave"),
  { key: "searxng", showModelField: false, showApiKey: false },
  {
    ...keyOnlyRow("composio"),
    managedAt: {
      href: "/settings/integrations-setup",
      label: "Open Integrations setup",
    },
  },
  keyOnlyRow("e2b"),
  keyOnlyRow("resend"),
  keyOnlyRow("cloudinary"),
  keyOnlyRow("google_oauth"),
  keyOnlyRow("firecrawl"),
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

/** One feature as Settings shows it: what it runs on now and the providers that can upgrade it. */
export interface FeatureGroup {
  key: ProviderFeature;
  spec: FeatureSpec;
  status: FeatureStatus | undefined;
  rows: CatalogProviderRow[];
}

/** The catalog's features in order, each with its offered providers, connected ones first. */
export function groupProvidersByFeature(
  catalog: ProviderCatalog,
  status: SetupStatus | undefined,
): FeatureGroup[] {
  // The API keys features by exactly the ProviderFeature values.
  const features = Object.entries(catalog.features) as [
    ProviderFeature,
    FeatureSpec,
  ][];
  return features.map(([key, spec]) => ({
    key,
    spec,
    status: status?.features[key],
    rows: spec.providers
      .filter((provider) => isProviderOffered(status, provider))
      .map((provider) => resolveProviderRow(provider, catalog))
      .toSorted(
        (a, b) =>
          Number(isProviderConfigured(status, b.key)) -
          Number(isProviderConfigured(status, a.key)),
      ),
  }));
}
