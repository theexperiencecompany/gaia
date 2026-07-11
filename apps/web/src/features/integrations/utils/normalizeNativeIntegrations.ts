import type { CommunityIntegration, Integration } from "../types";

/**
 * Normalize platform integrations from /integrations/config to the
 * CommunityIntegration shape used by marketplace cards. Shared between the
 * client API layer and the server-rendered /marketplace hub.
 */
export function normalizeNativeIntegrations(
  integrations: Integration[],
): CommunityIntegration[] {
  return integrations
    .filter((i) => i.source === "platform" && i.available !== false)
    .sort((a, b) => (b.displayPriority ?? 0) - (a.displayPriority ?? 0))
    .map((i) => ({
      integrationId: i.id,
      slug: i.slug,
      name: i.name,
      description: i.description,
      category: i.category,
      iconUrl: i.iconUrl ?? null,
      cloneCount: 0,
      toolCount: i.tools?.length ?? 0,
      tools: (i.tools ?? []).map((t) => ({
        name: t.name,
        description: t.description ?? null,
      })),
      publishedAt: null,
      creator: null,
      source: "platform" as const,
    }));
}

/** Page size for the marketplace community listing (server + client). */
export const MARKETPLACE_ITEMS_PER_PAGE = 18;
