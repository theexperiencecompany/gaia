import type {
  FeatureSpec,
  FeatureStatus,
  ProviderFeature,
} from "@gaia/shared/api/generated";
import { COMPOSIO_SETUP_PATH } from "@/features/settings/api/composioSetupApi";
import type {
  CredentialProvider,
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import {
  isProviderConfigured,
  isProviderOffered,
} from "@/features/settings/hooks/useSetupStatus";
import type { CustomPresetKey } from "@/features/settings/utils/customPresets";
import {
  type CatalogProvider,
  resolveCatalogProvider,
} from "@/features/settings/utils/providerCatalog";

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
      href: COMPOSIO_SETUP_PATH,
      label: "Open Integrations setup",
    },
  },
  keyOnlyRow("e2b"),
  keyOnlyRow("resend"),
  keyOnlyRow("cloudinary"),
  keyOnlyRow("google_oauth"),
  keyOnlyRow("firecrawl"),
  keyOnlyRow("openweather"),
  keyOnlyRow("llamaparse"),
  keyOnlyRow("github"),
];

export type CustomPresetId = CustomPresetKey | "manual";

function resolveProviderRow(
  key: CredentialProvider,
  catalog: ProviderCatalog,
): CatalogProviderRow {
  const row = PROVIDER_ROWS.find((r) => r.key === key);
  if (!row) throw new Error(`No settings row for provider "${key}"`);
  return { ...resolveCatalogProvider(key, catalog), ...row };
}

/** One feature as Settings and the wizard show it: what it runs on now and the providers that can upgrade it. */
export interface FeatureGroup {
  key: ProviderFeature;
  spec: FeatureSpec;
  status: FeatureStatus | undefined;
  rows: CatalogProviderRow[];
}

/** Query param that scrolls Settings > Providers & Tools to one feature's card. */
export const FEATURE_FOCUS_PARAM = "feature";

/** The DOM id of a feature's row, so a link can scroll it into view. */
export function featureAnchorId(feature: ProviderFeature): string {
  return `provider-feature-${feature}`;
}

/** The Settings link that opens one feature's provider card. */
export function providerFeatureHref(feature: ProviderFeature): string {
  return `/settings/providers?${FEATURE_FOCUS_PARAM}=${feature}`;
}

/** One feature with its offered providers, connected ones first. */
export function resolveFeatureGroup(
  key: ProviderFeature,
  catalog: ProviderCatalog,
  status: SetupStatus | undefined,
): FeatureGroup {
  const spec = catalog.features[key];
  if (!spec) throw new Error(`Provider catalog has no feature "${key}"`);
  return {
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
  };
}

/** The catalog's features in order. */
export function groupProvidersByFeature(
  catalog: ProviderCatalog,
  status: SetupStatus | undefined,
): FeatureGroup[] {
  // The API keys features by exactly the ProviderFeature values.
  const keys = Object.keys(catalog.features) as ProviderFeature[];
  return keys.map((key) => resolveFeatureGroup(key, catalog, status));
}

/** The provider serving the feature now, else the first connected one, else the first offered. */
export function initialPickedProvider(
  group: FeatureGroup,
): CatalogProviderRow | undefined {
  const serving = group.status?.in_use.find((engine) =>
    group.rows.some((row) => row.key === engine),
  );
  return group.rows.find((row) => row.key === serving) ?? group.rows[0];
}
