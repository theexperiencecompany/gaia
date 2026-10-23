import type { Metadata } from "next";
import { Suspense } from "react";

import JsonLd from "@/components/seo/JsonLd";
import { MarketplaceDirectory } from "@/features/integrations/components/MarketplaceDirectory";
import {
  getAllCommunityIntegrations,
  getNativeIntegrations,
} from "@/features/integrations/lib/serverMarketplaceApi";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

import { IntegrationsPageClient } from "./client";

export const metadata: Metadata = generatePageMetadata({
  title: "AI Integration Marketplace - Connect Your Tools to GAIA",
  description:
    "Browse AI integrations for productivity, communication, and developer tools. Automate Gmail, Slack, Notion, GitHub and more with GAIA's AI-powered MCP integration marketplace. Free to use.",
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

const TOP_INTEGRATIONS_IN_SCHEMA = 10;

export default async function MarketplacePage() {
  const [native, community] = await Promise.all([
    getNativeIntegrations(),
    getAllCommunityIntegrations(),
  ]);
  const webPageSchema = generateWebPageSchema(
    "AI Integration Marketplace - Connect Your Tools to AI",
    "Browse AI integrations for productivity, communication, and developer tools. Automate Gmail, Slack, Notion, GitHub and more with GAIA's AI-powered MCP integration marketplace.",
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
  // Popular-first, so the ItemList names the integrations people actually use.
  const topIntegrations = community.slice(0, TOP_INTEGRATIONS_IN_SCHEMA);
  const itemListSchema =
    topIntegrations.length > 0
      ? generateItemListSchema(
          topIntegrations.map((integration) => ({
            name: `${integration.name} AI Integration`,
            url: `${siteConfig.url}/marketplace/${integration.slug}`,
          })),
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
      <div className="min-h-screen pt-16 pb-16">
        <div className="relative z-1 mx-auto mt-10 max-w-7xl px-6">
          <div className="mb-12">
            <h1 className="mb-4 font-serif text-5xl font-normal text-foreground md:text-7xl">
              Integration Marketplace
            </h1>
            <p className="max-w-2xl text-lg font-light text-foreground-500">
              Discover and automate your favorite tools with AI. Browse
              community-built MCP integrations to connect Gmail, Slack, Notion,
              GitHub, and many more services to your AI assistant.
            </p>
          </div>
          {/* useSearchParams opts the grid into client rendering; the header
              and directory around it stay in the prerendered HTML. */}
          <Suspense>
            <IntegrationsPageClient />
          </Suspense>
          <MarketplaceDirectory native={native} community={community} />
        </div>
        <FinalSection />
      </div>
    </>
  );
}
