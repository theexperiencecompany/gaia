import type { ProviderCatalog } from "@/features/settings/api/providersApi";
import { featureEngineLabel } from "@/features/settings/utils/providerCatalog";
import type { FeatureGroup } from "./providerRows";

export type FeatureTone = "working" | "off" | "unavailable";

/** A feature's state as one badge and one line: whether it works, and on what. */
export interface FeatureState {
  tone: FeatureTone;
  badge: string;
  summary: string;
}

const BADGES: Record<FeatureTone, string> = {
  working: "Working",
  off: "Not set up",
  unavailable: "Not available here",
};

export function featureState(
  group: FeatureGroup,
  catalog: ProviderCatalog,
): FeatureState {
  const { spec, status } = group;
  if (status?.available === false) {
    return {
      tone: "unavailable",
      badge: BADGES.unavailable,
      summary: spec.self_host_gap?.reason ?? spec.description,
    };
  }
  const [engine] = status?.in_use ?? [];
  if (status?.working && engine) {
    const label = featureEngineLabel(engine, spec, catalog);
    const free = engine === spec.built_in?.engine ? ", free" : "";
    return {
      tone: "working",
      badge: BADGES.working,
      summary: `${label}${free}`,
    };
  }
  return { tone: "off", badge: BADGES.off, summary: spec.description };
}
