import type { CommunityIntegration } from "@/features/integrations/types";
import { type HubPage, paginateSections } from "@/lib/hubPagination";

export const MARKETPLACE_PATH = "/marketplace";

function byName(
  integrations: readonly CommunityIntegration[],
): CommunityIntegration[] {
  return [...integrations].sort((a, b) => a.name.localeCompare(b.name));
}

/** Community entries named like a native integration read "<Name> MCP", so no two directory links share text but not a destination. */
function distinctFromNative(
  community: readonly CommunityIntegration[],
  native: readonly CommunityIntegration[],
): CommunityIntegration[] {
  const nativeNames = new Set(native.map((integration) => integration.name));
  return community.map((integration) =>
    nativeNames.has(integration.name)
      ? { ...integration, name: `${integration.name} MCP` }
      : integration,
  );
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
        items: byName(distinctFromNative(community, native)),
      },
    ].filter((section) => section.items.length > 0),
  );
}
