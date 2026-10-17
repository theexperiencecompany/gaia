import type { IntegrationsConfigResponse } from "@shared/api/generated";
import type { Metadata } from "next";
import { Suspense } from "react";

import JsonLd from "@/components/seo/JsonLd";
import type {
  CommunityIntegration,
  CommunityIntegrationsResponse,
} from "@/features/integrations/types";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

import { IntegrationsPageClient } from "./client";

export const metadata: Metadata = generatePageMetadata({
  title: "AI Integration Marketplace - Connect Your Tools to GAIA",
  description:
    "Browse 50+ AI integrations for productivity, communication, and developer tools. Automate Gmail, Slack, Notion, GitHub and more with GAIA's AI-powered MCP integration marketplace. Free to use.",
  path: "/marketplace",
  image: "/api/og/integrations",
  keywords: [
    "AI integration marketplace",
    "MCP integrations",
    "AI integrations",
    "automate tools with AI",
    "AI assistant integrations",
    "connect apps to AI",
    "MCP servers",
    "AI automation tools",
    "productivity AI integrations",
    "GAIA integrations",
    "AI-powered workflow integrations",
    "community integrations",
    "free AI integrations",
  ],
});

export const revalidate = 3600;

interface InitialMarketplace {
  readonly native: CommunityIntegration[];
  readonly community: CommunityIntegration[];
  readonly total: number;
}

/**
 * First grid page, fetched server-side so crawlers see real detail links in
 * the SSR HTML instead of a client-only grid. Mirrors the client's
 * getNativeIntegrations mapping and the community first page (sort=popular,
 * limit=18). Dedupes by integrationId; fail-safe returns null (client-only
 * fallback, ItemList already does this).
 */
async function getInitialMarketplace(): Promise<InitialMarketplace | null> {
  const baseUrl = getServerApiBaseUrl();
  if (!baseUrl) return null;

  try {
    const [configResponse, communityResponse] = await Promise.all([
      fetch(`${baseUrl}/integrations/config`, {
        next: { revalidate: 3600 },
      }),
      fetch(`${baseUrl}/integrations/community?sort=popular&limit=18`, {
        next: { revalidate: 3600 },
      }),
    ]);
    if (!configResponse.ok || !communityResponse.ok) return null;

    const config = (await configResponse.json()) as IntegrationsConfigResponse;
    const community =
      (await communityResponse.json()) as CommunityIntegrationsResponse;

    const native: CommunityIntegration[] = config.integrations
      .filter((item) => item.source === "platform" && item.available !== false)
      .sort((a, b) => b.displayPriority - a.displayPriority)
      .map((item) => ({
        integrationId: item.id,
        slug: item.slug,
        name: item.name,
        description: item.description,
        category: item.category,
        // The config endpoint carries no icon or tool list; cards resolve the
        // icon by slug and the tool list is fetched per integration on demand.
        iconUrl: null,
        cloneCount: 0,
        toolCount: 0,
        tools: [],
        publishedAt: null,
        creator: null,
        source: "platform" as const,
      }));

    const nativeIds = new Set(native.map((item) => item.integrationId));
    const seen = new Set<string>();
    const communityItems = (community.integrations ?? []).filter((item) => {
      if (
        !item ||
        nativeIds.has(item.integrationId) ||
        seen.has(item.integrationId)
      ) {
        return false;
      }
      seen.add(item.integrationId);
      return true;
    });

    return {
      native,
      community: communityItems,
      total: community.total ?? communityItems.length,
    };
  } catch (error) {
    console.error("[marketplace] Failed to fetch initial grid:", error);
    return null;
  }
}

/** Most popular integrations for the ItemList rich result (real URLs). */
async function getTopIntegrations(): Promise<CommunityIntegration[]> {
  const baseUrl = getServerApiBaseUrl();
  if (!baseUrl) return [];

  try {
    const response = await fetch(
      `${baseUrl}/integrations/community?sort=popular&limit=10`,
      { next: { revalidate: 3600 } },
    );
    if (!response.ok) return [];
    const data = (await response.json()) as CommunityIntegrationsResponse;
    return (data.integrations ?? []).slice(0, 10);
  } catch (error) {
    console.error("[marketplace] Failed to fetch top integrations:", error);
    return [];
  }
}

export default async function MarketplacePage({
  searchParams,
}: {
  readonly searchParams?: Promise<{
    readonly search?: string;
    readonly category?: string;
  }>;
}) {
  const webPageSchema = generateWebPageSchema(
    "AI Integration Marketplace - Connect Your Tools to AI",
    "Browse 50+ AI integrations for productivity, communication, and developer tools. Automate Gmail, Slack, Notion, GitHub and more with GAIA's AI-powered MCP integration marketplace.",
    `${siteConfig.url}/marketplace`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Marketplace", url: `${siteConfig.url}/marketplace` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Marketplace", url: `${siteConfig.url}/marketplace` },
  ]);
  // ItemList must point at crawlable integration URLs, not the hub itself.
  // When the backend is unreachable at build time, omit it rather than
  // emitting self-referential entries.
  const topIntegrations = await getTopIntegrations();
  const itemListSchema =
    topIntegrations.length > 0
      ? generateItemListSchema(
          topIntegrations.map((integration) => ({
            name: `${integration.name} AI Integration`,
            url: `${siteConfig.url}/marketplace/${integration.slug}`,
            description: integration.description,
          })),
          "SoftwareApplication",
        )
      : null;

  // SSR the first grid page only for the unfiltered view: with ?search= or a
  // ?category= the client filters locally, so server initials would mismatch
  // and cause a hydration flash. Backend down => client-only fallback.
  const params = (await searchParams) ?? {};
  const hasFilter =
    (params.search ?? "") !== "" ||
    (params.category !== undefined && params.category !== "all");
  const initial = hasFilter ? null : await getInitialMarketplace();

  return (
    <>
      {/* No FAQPage schema here: this list page renders no visible FAQs,
          and FAQ rich results require the questions to be on the page. */}
      <JsonLd
        data={
          itemListSchema
            ? [webPageSchema, breadcrumbSchema, itemListSchema]
            : [webPageSchema, breadcrumbSchema]
        }
      />
      <Suspense>
        <IntegrationsPageClient
          initialNativeIntegrations={initial?.native}
          initialIntegrations={initial?.community}
          initialTotal={initial?.total}
        />
      </Suspense>
    </>
  );
}
