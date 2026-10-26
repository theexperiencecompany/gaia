import type { IntegrationCombo } from "@/features/integrations/data/combosData";
import { circularNeighbours } from "@/lib/circularNeighbours";

/** How many of an app's other combos each combo page links, per app it pairs. */
const RELATED_COMBOS_PER_APP = 3;

/** The combos after this one around its app's ring: every combo of the app in slug order, wrapping at the end. */
function nextInAppRing(
  combo: IntegrationCombo,
  appSlug: string,
  allCombos: readonly IntegrationCombo[],
): IntegrationCombo[] {
  const ring = allCombos
    .filter((c) => c.toolASlug === appSlug || c.toolBSlug === appSlug)
    .sort((a, b) => a.slug.localeCompare(b.slug));
  const offsets = Array.from(
    { length: Math.min(RELATED_COMBOS_PER_APP, ring.length - 1) },
    (_, index) => index + 1,
  );
  return circularNeighbours(
    ring,
    ring.findIndex((c) => c.slug === combo.slug),
    offsets,
  );
}

/**
 * The next combos around each of this combo's two app rings.
 * Each combo is linked by its predecessors in both rings, so one with an app
 * in three or more combos is linked from at least two other combo pages.
 */
export function relatedCombos(
  combo: IntegrationCombo,
  allCombos: readonly IntegrationCombo[],
): IntegrationCombo[] {
  return [
    ...nextInAppRing(combo, combo.toolASlug, allCombos),
    ...nextInAppRing(combo, combo.toolBSlug, allCombos),
  ];
}
