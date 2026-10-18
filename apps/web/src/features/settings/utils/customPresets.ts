import type { ProviderPreset } from "@gaia/shared/api/generated";
import type {
  ProviderCatalog,
  ProviderConfigBody,
} from "@/features/settings/api/providersApi";

/** Gateway id sent as `preset` on the provider body. */
export type CustomPresetKey = NonNullable<ProviderConfigBody["preset"]>;

/** One OpenAI-compatible gateway offered as a chip inside the Custom lane. */
export type CustomPreset = ProviderPreset & { key: CustomPresetKey };

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
