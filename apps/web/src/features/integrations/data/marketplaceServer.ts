import type { IntegrationsConfigResponse } from "@shared/api/generated";
import { cache } from "react";

import type {
  CommunityIntegration,
  CommunityIntegrationsResponse,
  PublicIntegrationResponse,
} from "@/features/integrations/types";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";

const DEFAULT_REVALIDATE_SECONDS = 3600;
const DETAIL_REVALIDATE_SECONDS = 60;
const REQUEST_TIMEOUT_MS = 10_000;
/** The community endpoint caps `limit` at 100. */
const COMMUNITY_PAGE_SIZE = 100;

type CommunitySort = "popular" | "recent" | "name";

/** GET backend JSON for a prerendered page: null on 404 or with no backend configured; any other failure throws. */
async function fetchBackendJson<T>(
  path: string,
  revalidate = DEFAULT_REVALIDATE_SECONDS,
): Promise<T | null> {
  const baseUrl = getServerApiBaseUrl();
  if (!baseUrl) return null;
  const response = await fetch(`${baseUrl}${path}`, {
    next: { revalidate },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`[marketplace] GET ${path} returned ${response.status}`);
  }
  return (await response.json()) as T;
}

/** One integration's public detail by slug or id; null when it does not exist. */
export const getPublicIntegration = cache((identifier: string) =>
  fetchBackendJson<PublicIntegrationResponse>(
    `/integrations/public/${encodeURIComponent(identifier)}`,
    DETAIL_REVALIDATE_SECONDS,
  ),
);

/** GAIA's first-party integrations, highest display priority first, as marketplace cards. */
export const getNativeIntegrations = cache(
  async (): Promise<CommunityIntegration[]> => {
    const config = await fetchBackendJson<IntegrationsConfigResponse>(
      "/integrations/config",
    );
    return (config?.integrations ?? [])
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
}): Promise<CommunityIntegrationsResponse | null> {
  const query = new URLSearchParams({
    sort: options.sort,
    limit: String(options.limit),
    offset: String(options.offset ?? 0),
  });
  if (options.category) query.set("category", options.category);
  return fetchBackendJson<CommunityIntegrationsResponse>(
    `/integrations/community?${query}`,
  );
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
      const items = page?.integrations ?? [];
      all.push(...items);
      if (
        items.length < COMMUNITY_PAGE_SIZE ||
        all.length >= (page?.total ?? 0)
      )
        return all;
    }
  },
);

/** Community workflows that use an integration. */
export async function getIntegrationWorkflows(
  integrationId: string,
  limit: number,
): Promise<CommunityWorkflow[]> {
  const data = await fetchBackendJson<{ workflows?: CommunityWorkflow[] }>(
    `/integrations/public/${encodeURIComponent(integrationId)}/workflows?limit=${limit}`,
    DETAIL_REVALIDATE_SECONDS,
  );
  return (data?.workflows ?? []).slice(0, limit);
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
  if (
    slugIndexCache &&
    now - slugIndexCache.builtAt < DEFAULT_REVALIDATE_SECONDS * 1000
  ) {
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
