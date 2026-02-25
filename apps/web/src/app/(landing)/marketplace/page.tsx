import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import { marketplaceFAQs } from "@/lib/page-faqs";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

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

export default function MarketplacePage() {
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
      <IntegrationsPageClient />
    </>
  );
}
