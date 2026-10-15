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

export default async function MarketplacePage() {
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
          "Product",
        )
      : null;

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
        <IntegrationsPageClient />
      </Suspense>
    </>
  );
}
