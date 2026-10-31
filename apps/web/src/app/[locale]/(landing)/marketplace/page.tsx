import type { Metadata } from "next";
import { Suspense } from "react";

import JsonLd from "@/components/seo/JsonLd";
import { MarketplaceDirectory } from "@/features/integrations/components/MarketplaceDirectory";
import { marketplaceDirectoryPages } from "@/features/integrations/lib/marketplaceDirectoryPages";
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

const PAGE_TITLE = "AI Integration Marketplace: Connect Your Tools to GAIA";
const PAGE_DESCRIPTION =
  "Browse AI integrations and MCP servers for Gmail, Slack, Notion, GitHub, and more. Connect a tool to GAIA and automate it in plain English.";

export const metadata: Metadata = generatePageMetadata({
  title: PAGE_TITLE,
  description: PAGE_DESCRIPTION,
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
  ],
});

export const revalidate = 3600;

const TOP_INTEGRATIONS_IN_SCHEMA = 10;

export default async function MarketplacePage() {
  const [native, community] = await Promise.all([
    getNativeIntegrations(),
    getAllCommunityIntegrations(),
  ]);
  const directoryPages = marketplaceDirectoryPages(native, community);
  const webPageSchema = generateWebPageSchema(
    PAGE_TITLE,
    PAGE_DESCRIPTION,
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
              GAIA&apos;s integration marketplace is the catalogue of tools GAIA
              can connect to. It combines native integrations such as Gmail,
              Slack, Notion, GitHub, and Google Calendar with community-built
              MCP servers that extend the assistant to other services. Each
              listing explains what the integration exposes and how to connect
              it to your account. Use the search field to find a tool by name,
              filter by category, and sort by popularity, recency, or name. The
              directory below lists the integrations alphabetically, with
              further pages linked at the bottom, so you can jump straight to a
              detail page. If a tool is missing, MCP is the extension path:
              build the server, publish it, and it can appear here for other
              users.
            </p>
          </div>
          {/* useSearchParams opts the grid into client rendering; the header
              and directory around it stay in the prerendered HTML. */}
          <Suspense>
            <IntegrationsPageClient />
          </Suspense>
          {directoryPages[0] && (
            <MarketplaceDirectory
              hubPage={directoryPages[0]}
              totalPages={directoryPages.length}
            />
          )}
        </div>
        <FinalSection />
      </div>
    </>
  );
}
