import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import type { IntegrationConfigResponse } from "@/features/integrations/api/integrationsApi";
import type { CommunityIntegrationsResponse } from "@/features/integrations/types";
import {
  MARKETPLACE_ITEMS_PER_PAGE,
  normalizeNativeIntegrations,
} from "@/features/integrations/utils/normalizeNativeIntegrations";
import { marketplaceFAQs } from "@/lib/page-faqs";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

import { IntegrationsPageClient, type MarketplaceInitialData } from "./client";

/**
 * Server-fetch the first page of the marketplace so the integration cards —
 * and the /marketplace/[slug] links they carry — are in the crawlable HTML.
 * Without this the hub ships skeletons and Google sees no internal links to
 * the integration detail pages.
 */
async function getInitialMarketplaceData(): Promise<MarketplaceInitialData | null> {
  const baseUrl = getServerApiBaseUrl();
  if (!baseUrl) return null;

  try {
    const [communityRes, configRes] = await Promise.all([
      fetch(
        `${baseUrl}/integrations/community?sort=popular&limit=${MARKETPLACE_ITEMS_PER_PAGE}&offset=0`,
        { next: { revalidate: 3600 } },
      ),
      fetch(`${baseUrl}/integrations/config`, {
        next: { revalidate: 3600 },
      }),
    ]);

    if (!communityRes.ok) return null;
    const community =
      (await communityRes.json()) as CommunityIntegrationsResponse;
    const config = configRes.ok
      ? ((await configRes.json()) as IntegrationConfigResponse)
      : null;

    return {
      integrations: community.integrations ?? [],
      total: community.total ?? 0,
      native: config ? normalizeNativeIntegrations(config.integrations) : [],
    };
  } catch (error) {
    console.error("[marketplace] Failed to fetch initial listing:", error);
    return null;
  }
}

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

export default async function MarketplacePage() {
  const initialData = await getInitialMarketplaceData();
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
  const itemListSchema = generateItemListSchema(
    [
      {
        name: "Email AI Integrations",
        url: `${siteConfig.url}/marketplace`,
        description:
          "Automate Gmail, Outlook, and email workflows with AI. Let GAIA triage, draft, and manage your inbox.",
      },
      {
        name: "Calendar AI Integrations",
        url: `${siteConfig.url}/marketplace`,
        description:
          "AI-powered calendar management for Google Calendar and Outlook. Automate scheduling and meeting prep.",
      },
      {
        name: "Productivity AI Integrations",
        url: `${siteConfig.url}/marketplace`,
        description:
          "Connect Notion, Todoist, Linear, and Asana to AI. Automate task management and project workflows.",
      },
      {
        name: "Developer AI Integrations",
        url: `${siteConfig.url}/marketplace`,
        description:
          "AI integrations for GitHub, GitLab, and developer tools. Automate code reviews, issues, and CI/CD.",
      },
      {
        name: "Communication AI Integrations",
        url: `${siteConfig.url}/marketplace`,
        description:
          "Connect Slack, Discord, and Teams to AI. Automate messages, notifications, and team communication.",
      },
    ],
    "Product",
  );

  const faqSchema = generateFAQSchema(marketplaceFAQs);

  return (
    <>
      <JsonLd
        data={[webPageSchema, breadcrumbSchema, itemListSchema, faqSchema]}
      />
      <IntegrationsPageClient initialData={initialData} />
    </>
  );
}
