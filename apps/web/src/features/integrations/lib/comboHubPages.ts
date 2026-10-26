import type { IntegrationCombo } from "@/features/integrations/data/combosData";
import {
  type HubPage,
  type HubSection,
  paginateSections,
} from "@/lib/hubPagination";

/** The /automate hub's pages: combos grouped by their first app, apps A to Z. */
export function comboHubPages(
  combos: readonly IntegrationCombo[],
): HubPage<IntegrationCombo>[] {
  const byApp = new Map<string, IntegrationCombo[]>();
  for (const combo of combos) {
    byApp.set(combo.toolASlug, [...(byApp.get(combo.toolASlug) ?? []), combo]);
  }
  const sections: HubSection<IntegrationCombo>[] = [...byApp]
    .map(([appSlug, appCombos]) => ({
      id: `app-${appSlug}`,
      label: appCombos[0].toolA,
      items: appCombos,
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
  return paginateSections(sections);
}
