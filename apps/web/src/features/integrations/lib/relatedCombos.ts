import type { IntegrationCombo } from "@/features/integrations/data/combosData";
import { circularNeighbours } from "@/lib/circularNeighbours";
import {
  type ComboApp,
  type ComboAppGroup,
  comboAppGroups,
  comboAppsOf,
} from "./comboApps";

/** How many of an app's other combos each combo page links, per app it pairs. */
const RELATED_COMBOS_PER_APP = 3;

export interface RelatedComboRow {
  readonly app: ComboApp;
  /** How many combos the app has in all, for the link to its page. */
  readonly total: number;
  readonly combos: readonly IntegrationCombo[];
}

function nextInAppRing(
  combo: IntegrationCombo,
  group: ComboAppGroup,
): IntegrationCombo[] {
  const ring = group.combos;
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
 * One row per app of this combo: the next combos around that app's ring (its combos in slug order, wrapping).
 * Each combo is linked by its predecessors in both rings, so one with an app
 * in three or more combos is linked from at least two other combo pages.
 */
export function relatedComboRows(
  combo: IntegrationCombo,
  allCombos: readonly IntegrationCombo[],
): RelatedComboRow[] {
  const groups = new Map(
    comboAppGroups(allCombos).map((group) => [group.slug, group]),
  );
  return comboAppsOf(combo).flatMap((app) => {
    const group = groups.get(app.slug);
    return group
      ? [
          {
            app,
            total: group.combos.length,
            combos: nextInAppRing(combo, group),
          },
        ]
      : [];
  });
}
