import type {
  CommunityIntegration,
  CommunityIntegrationsResponse,
  PublicIntegrationResponse,
} from "@/features/integrations/types";
import {
  serverApi,
  serverData,
  serverDataOrNull,
  sharedAcrossBuild,
} from "@/lib/api/server";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";

/** The community endpoint caps `limit` at 100. */
const COMMUNITY_PAGE_SIZE = 100;

type CommunitySort = "popular" | "recent" | "name";

/** One integration's public detail by slug or id; null when it does not exist. */
export const getPublicIntegration = sharedAcrossBuild(
  async (identifier: string): Promise<PublicIntegrationResponse | null> => {
    const client = serverApi();
    if (!client) return null;
    const result = await client.GET(
      "/api/v1/integrations/public/{identifier}",
      {
        params: { path: { identifier } },
      },
    );
    return serverDataOrNull(result);
  },
);

/** GAIA's first-party integrations, highest display priority first, as marketplace cards. */
export const getNativeIntegrations = sharedAcrossBuild(
  async (): Promise<CommunityIntegration[]> => {
    const client = serverApi();
    if (!client) return [];
    const config = serverData(
      await client.GET("/api/v1/integrations/config", {}),
    );
    return config.integrations
      .filter((item) => item.source === "platform" && item.available !== false)
      .sort((a, b) => b.displayPriority - a.displayPriority)
      .map((item) => ({
        integrationId: item.id,
        slug: item.slug,
        name: item.name,
        description: item.description,
        category: item.category,
        iconUrl: null,
        cloneCount: 0,
        toolCount: 0,
        tools: [],
        publishedAt: null,
        creator: null,
        source: "platform" as const,
      }));
  },
);

/** One page of community integrations. */
async function getCommunityIntegrations(options: {
  readonly sort: CommunitySort;
  readonly limit: number;
  readonly offset?: number;
  readonly category?: string;
}): Promise<CommunityIntegrationsResponse> {
  const client = serverApi();
  if (!client) return { integrations: [], total: 0, has_more: false };
  const result = await client.GET("/api/v1/integrations/community", {
    params: {
      query: {
        sort: options.sort,
        limit: options.limit,
        offset: options.offset ?? 0,
        category: options.category,
      },
    },
  });
  return serverData(result);
}

/** Every published community integration, walking the paginated endpoint to its total. */
export const getAllCommunityIntegrations = sharedAcrossBuild(
  async (sort: CommunitySort = "popular"): Promise<CommunityIntegration[]> => {
    const all: CommunityIntegration[] = [];
    for (let offset = 0; ; offset += COMMUNITY_PAGE_SIZE) {
      const page = await getCommunityIntegrations({
        sort,
        limit: COMMUNITY_PAGE_SIZE,
        offset,
      });
      const items = page.integrations;
      all.push(...items);
      if (items.length < COMMUNITY_PAGE_SIZE || all.length >= page.total)
        return all;
    }
  },
);

/** Community workflows that use an integration. */
export const getIntegrationWorkflows = sharedAcrossBuild(
  async (
    integrationId: string,
    limit: number,
  ): Promise<CommunityWorkflow[]> => {
    const client = serverApi();
    if (!client) return [];
    const result = await client.GET(
      "/api/v1/integrations/public/{identifier}/workflows",
      {
        params: { path: { identifier: integrationId }, query: { limit } },
      },
    );
    return (serverDataOrNull(result)?.workflows ?? []).slice(0, limit);
  },
);

/** Marketing pages spell tools "google-calendar"; the marketplace spells them "googlecalendar". */
function normalizeToolSlug(slug: string): string {
  return slug.toLowerCase().replace(/[-_\s]/g, "");
}

/** Normalized tool slug to live marketplace integration. */
async function getMarketplaceSlugIndex(): Promise<
  ReadonlyMap<string, CommunityIntegration>
> {
  const [native, community] = await Promise.all([
    getNativeIntegrations(),
    getAllCommunityIntegrations(),
  ]);
  return new Map(
    [...native, ...community].map((item) => [
      normalizeToolSlug(item.slug),
      item,
    ]),
  );
}

/** The marketplace page for a tool a marketing page mentions, or null when GAIA has no such integration. */
export async function getMarketplacePath(
  toolSlug: string,
): Promise<string | null> {
  const index = await getMarketplaceSlugIndex();
  const integration = index.get(normalizeToolSlug(toolSlug));
  return integration === undefined ? null : `/marketplace/${integration.slug}`;
}

/** The live marketplace integration with exactly this slug, or null when the marketplace has none. */
export async function getMarketplaceIntegration(
  slug: string,
): Promise<CommunityIntegration | null> {
  const index = await getMarketplaceSlugIndex();
  const integration = index.get(normalizeToolSlug(slug));
  return integration?.slug === slug ? integration : null;
}
