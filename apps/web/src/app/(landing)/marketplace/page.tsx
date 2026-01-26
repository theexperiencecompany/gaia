import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

import { IntegrationsPageClient } from "./client";

export const metadata: Metadata = generatePageMetadata({
  title: "Integration Marketplace",
  description:
    "Discover and clone MCP integrations built by the community. Connect AI tools to your favorite services.",
  path: "/marketplace",
  image: "/api/og/integrations",
  keywords: [
    "MCP integrations",
    "AI integrations",
    "community integrations",
    "MCP servers",
    "AI tools",
    "GAIA integrations",
    "integration marketplace",
  ],
});

export const revalidate = 3600;

export default function MarketplacePage() {
  const webPageSchema = generateWebPageSchema(
    "Integration Marketplace",
    "Discover and clone MCP integrations built by the GAIA community. Connect AI tools to your favorite services.",
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
        name: "Email Integrations",
        url: `${siteConfig.url}/marketplace`,
        description: "Connect GAIA to Gmail, Outlook, and more",
      },
      {
        name: "Calendar Integrations",
        url: `${siteConfig.url}/marketplace`,
        description: "Sync with Google Calendar, Outlook Calendar",
      },
      {
        name: "Productivity Tools",
        url: `${siteConfig.url}/marketplace`,
        description: "Notion, Todoist, Linear, and more",
      },
    ],
    "Product",
  );

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema, itemListSchema]} />
      <IntegrationsPageClient />
    </>
  );
}
