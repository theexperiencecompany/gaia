import { cache } from "react";

import type {
  CommunityIntegration,
  CommunityIntegrationsResponse,
  PublicIntegrationResponse,
} from "@/features/integrations/types";
import { serverApi, serverData, serverDataOrNull } from "@/lib/api/server";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";

const REQUEST_TIMEOUT_MS = 10_000;
/** How long the tool-slug index serves before it is rebuilt. */
const SLUG_INDEX_TTL_MS = 3600 * 1000;
/** The community endpoint caps `limit` at 100. */
const COMMUNITY_PAGE_SIZE = 100;

type CommunitySort = "popular" | "recent" | "name";

/** One integration's public detail by slug or id; null when it does not exist. */
export const getPublicIntegration = cache(
  async (identifier: string): Promise<PublicIntegrationResponse | null> => {
    const client = serverApi();
    if (!client) return null;
    const result = await client.GET(
      "/api/v1/integrations/public/{identifier}",
      {
        params: { path: { identifier } },
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      },
    );
    return serverDataOrNull(result);
  },
);

/** GAIA's first-party integrations, highest display priority first, as marketplace cards. */
export const getNativeIntegrations = cache(
  async (): Promise<CommunityIntegration[]> => {
    const client = serverApi();
    if (!client) return [];
    const config = serverData(
      await client.GET("/api/v1/integrations/config", {
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      }),
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
export async function getCommunityIntegrations(options: {
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
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  return serverData(result);
}

/** Every published community integration, walking the paginated endpoint to its total. */
export const getAllCommunityIntegrations = cache(
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
export async function getIntegrationWorkflows(
  integrationId: string,
  limit: number,
): Promise<CommunityWorkflow[]> {
  const client = serverApi();
  if (!client) return [];
  const result = await client.GET(
    "/api/v1/integrations/public/{identifier}/workflows",
    {
      params: { path: { identifier: integrationId }, query: { limit } },
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    },
  );
  return (serverDataOrNull(result)?.workflows ?? []).slice(0, limit);
}

/** Marketing pages spell tools "google-calendar"; the marketplace spells them "googlecalendar". */
function normalizeToolSlug(slug: string): string {
  return slug.toLowerCase().replace(/[-_\s]/g, "");
}

let slugIndexCache:
  | {
      readonly builtAt: number;
      readonly index: Promise<ReadonlyMap<string, string>>;
    }
  | undefined;

/** Normalized tool slug to live marketplace slug, rebuilt hourly rather than fetched once per page. */
function getMarketplaceSlugIndex(): Promise<ReadonlyMap<string, string>> {
  const now = Date.now();
  if (slugIndexCache && now - slugIndexCache.builtAt < SLUG_INDEX_TTL_MS) {
    return slugIndexCache.index;
  }
  const index = Promise.all([
    getNativeIntegrations(),
    getAllCommunityIntegrations(),
  ]).then(
    ([native, community]) =>
      new Map(
        [...native, ...community].map((item) => [
          normalizeToolSlug(item.slug),
          item.slug,
        ]),
      ),
  );
  slugIndexCache = { builtAt: now, index };
  index.catch(() => {
    slugIndexCache = undefined;
  });
  return index;
}

/** The marketplace page for a tool a marketing page mentions, or null when GAIA has no such integration. */
export async function getMarketplacePath(
  toolSlug: string,
): Promise<string | null> {
  const index = await getMarketplaceSlugIndex();
  const slug = index.get(normalizeToolSlug(toolSlug));
  return slug === undefined ? null : `/marketplace/${slug}`;
}
