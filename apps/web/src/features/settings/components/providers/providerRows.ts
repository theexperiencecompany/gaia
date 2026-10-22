import type {
  FeatureSpec,
  FeatureStatus,
  ProviderFeature,
} from "@shared/api/generated";
import type {
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

export type CustomPresetId = CustomPresetKey | "manual";

/** One feature as Settings and the wizard show it: what it runs on now and the providers that can upgrade it. */
export interface FeatureGroup {
  key: ProviderFeature;
  spec: FeatureSpec;
  status: FeatureStatus | undefined;
  rows: CatalogProvider[];
}

/** Query param that scrolls Settings > Providers & Tools to one feature's card. */
export const FEATURE_FOCUS_PARAM = "feature";

/** The DOM id of a feature's row, so a link can scroll it into view. */
export function featureAnchorId(feature: ProviderFeature): string {
  return `provider-feature-${feature}`;
}

/** Settings > Providers & Tools. */
export const PROVIDERS_SETTINGS_PATH = "/settings/providers";

/** The Settings link that opens one feature's provider card. */
export function providerFeatureHref(feature: ProviderFeature): string {
  return `${PROVIDERS_SETTINGS_PATH}?${FEATURE_FOCUS_PARAM}=${feature}`;
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
      .map((provider) => resolveCatalogProvider(provider, catalog))
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
): CatalogProvider | undefined {
  const serving = group.status?.in_use.find((engine) =>
    group.rows.some((row) => row.key === engine),
  );
  return group.rows.find((row) => row.key === serving) ?? group.rows[0];
}
