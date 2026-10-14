import type {
  FeatureSpec,
  FeatureStatus,
  ProviderPreset,
} from "@gaia/shared/api/generated";
import type {
  CredentialProvider,
  ProviderCatalog,
} from "@/features/settings/api/providersApi";

/** A provider's catalog entry — its one source of display copy — plus whether it can be live-probed. */
export type CatalogProvider = ProviderPreset & {
  key: CredentialProvider;
  /** Only chat providers answer the test endpoint's models request. */
  connectionTestable: boolean;
};

export function resolveCatalogProvider(
  key: CredentialProvider,
  catalog: ProviderCatalog,
): CatalogProvider {
  const meta = catalog.providers[key];
  if (!meta) {
    throw new Error(`Provider catalog has no entry for "${key}"`);
  }
  return {
    ...meta,
    key,
    connectionTestable: catalog.llm_provider_keys.includes(key),
  };
}

/** What a feature runs on, by name: its built-in engine, or a provider from the catalog. */
export function featureEngineLabel(
  engine: FeatureStatus["in_use"][number],
  spec: FeatureSpec,
  catalog: ProviderCatalog,
): string {
  if (spec.built_in?.engine === engine) return spec.built_in.label;
  const provider = catalog.providers[engine];
  if (!provider) {
    throw new Error(`Provider catalog has no entry for "${engine}"`);
  }
  return provider.label;
}
