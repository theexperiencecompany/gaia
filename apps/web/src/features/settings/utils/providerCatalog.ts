import type { ProviderPreset } from "@gaia/shared/api/generated";
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
