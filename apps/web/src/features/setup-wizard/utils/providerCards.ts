import type { ProviderPreset } from "@gaia/shared/api/generated";
import type {
  ProviderCatalog,
  ProviderConfigBody,
} from "@/features/settings/api/providersApi";
import {
  type CatalogProvider,
  resolveCatalogProvider,
} from "@/features/settings/utils/providerCatalog";
import { LLM_PROVIDER_CARDS, type ProviderCardConfig } from "../constants";

/** Gateway id sent as `preset` on the provider body. */
export type CustomPresetKey = NonNullable<ProviderConfigBody["preset"]>;

/** One OpenAI-compatible gateway offered as a chip inside the Custom lane. */
export type CustomPreset = ProviderPreset & { key: CustomPresetKey };

/** A card's form config resolved against the live provider catalog. */
export type ProviderCard = CatalogProvider &
  ProviderCardConfig & { presets: readonly CustomPreset[] };

export function customPresetsFromCatalog(
  catalog: ProviderCatalog,
): CustomPreset[] {
  // The API keys custom_presets by exactly the ids its credential body's `preset` accepts.
  const entries = Object.entries(catalog.custom_presets) as [
    CustomPresetKey,
    ProviderPreset,
  ][];
  return entries.map(([key, preset]) => ({ ...preset, key }));
}

export function resolveProviderCard(
  card: ProviderCardConfig,
  catalog: ProviderCatalog,
): ProviderCard {
  return {
    ...resolveCatalogProvider(card.key, catalog),
    ...card,
    presets: card.hasPresets ? customPresetsFromCatalog(catalog) : [],
  };
}

/** The chat-capable provider cards, in the catalog's priority order. */
export function resolveLlmProviderCards(
  catalog: ProviderCatalog,
): ProviderCard[] {
  return catalog.llm_provider_keys.map((key) => {
    const card = LLM_PROVIDER_CARDS.find((c) => c.key === key);
    if (!card) {
      throw new Error(`No setup card for LLM provider "${key}"`);
    }
    return resolveProviderCard(card, catalog);
  });
}
