import type { ProviderPreset } from "@gaia/shared/api/generated";
import type {
  ProviderCatalog,
  ProviderConfigBody,
} from "@/features/settings/api/providersApi";
import { LLM_PROVIDER_CARDS, type ProviderCardConfig } from "../constants";

/** Gateway id sent as `preset` on the provider body. */
export type CustomPresetKey = NonNullable<ProviderConfigBody["preset"]>;

/** One OpenAI-compatible gateway offered as a chip inside the Custom lane. */
export type CustomPreset = ProviderPreset & { key: CustomPresetKey };

/** A card's static copy resolved against the live provider catalog. */
export interface ProviderCard extends ProviderCardConfig {
  /** Prefilled base URL; empty when the provider has no configurable endpoint. */
  defaultBaseUrl: string;
  /** Model the backend runs when none is stored — a hint, never saved implicitly. */
  defaultModel: string;
  presets: readonly CustomPreset[];
}

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
  const meta = catalog.providers[card.key];
  if (!meta) {
    throw new Error(`Provider catalog has no entry for "${card.key}"`);
  }
  return {
    ...card,
    defaultBaseUrl: meta.base_url,
    defaultModel: meta.default_model,
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
      throw new Error(`No setup card copy for LLM provider "${key}"`);
    }
    return resolveProviderCard(card, catalog);
  });
}
