import type { CommunityIntegration } from "@/features/integrations/types";
import { type HubPage, paginateSections } from "@/lib/hubPagination";

export const MARKETPLACE_PATH = "/marketplace";

function byName(
  integrations: readonly CommunityIntegration[],
): CommunityIntegration[] {
  return [...integrations].sort((a, b) => a.name.localeCompare(b.name));
}

/** The marketplace directory's pages: GAIA's own integrations, then the community's, each A to Z. */
export function marketplaceDirectoryPages(
  native: readonly CommunityIntegration[],
  community: readonly CommunityIntegration[],
): HubPage<CommunityIntegration>[] {
  return paginateSections(
    [
      { id: "directory-native", label: "Built by GAIA", items: byName(native) },
      {
        id: "directory-community",
        label: "Community",
        items: byName(community),
      },
    ].filter((section) => section.items.length > 0),
  );
}
