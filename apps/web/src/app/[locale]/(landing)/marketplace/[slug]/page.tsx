import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";

import JsonLd from "@/components/seo/JsonLd";
import { getComparison } from "@/features/comparisons/data/comparisonsData";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateHowToSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";

import { IntegrationDetailClient } from "./client";

export const revalidate = 60;

// Fetch integration data for metadata and page
// Backend accepts both slug and UUID for backward compatibility
const getIntegration = cache(async (slug: string) => {
  const baseUrl = getServerApiBaseUrl();
  if (!baseUrl) return null;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    const response = await fetch(`${baseUrl}/integrations/public/${slug}`, {
      next: { revalidate: 60 },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) return null;
    return response.json();
  } catch (error) {
    console.error(`[marketplace/${slug}] Failed to fetch integration:`, error);
    return null;
  }
});

// Fetch all integrations for static generation
async function getAllIntegrations() {
  const baseUrl = getServerApiBaseUrl();
  if (!baseUrl) return [];

  try {
    const isDev = process.env.NODE_ENV === "development";

    if (isDev) {
      const response = await fetch(
        `${baseUrl}/integrations/community?limit=50`,
        { next: { revalidate: 60 } },
      );
      if (!response.ok) return [];
      const data = await response.json();
      return data.integrations || [];
    }

    const { fetchAllPaginated } = await import("@/lib/fetchAll");
    const allIntegrations = await fetchAllPaginated(async (limit, offset) => {
      const response = await fetch(
        `${baseUrl}/integrations/community?limit=${limit}&offset=${offset}`,
        { next: { revalidate: 60 } },
      );
      if (!response.ok) return { items: [], total: 0, hasMore: false };

      const data = await response.json();
      return {
        items: data.integrations || [],
        total: data.total || 0,
        hasMore: data.hasMore !== false,
      };
    }, 100);

    return allIntegrations;
  } catch (error) {
    console.error("[marketplace] Failed to fetch integrations for SSG:", error);
    return [];
  }
}

async function getNativeIntegrationSlugs(): Promise<string[]> {
  const baseUrl = getServerApiBaseUrl();
  if (!baseUrl) return [];

  try {
    const response = await fetch(`${baseUrl}/integrations/config`, {
      next: { revalidate: 60 },
    });
    if (!response.ok) return [];
    const data = await response.json();
    return (data.integrations as Array<{ id: string; available?: boolean }>)
      .filter((i) => i.id && i.available !== false)
      .map((i) => i.id);
  } catch (error) {
    console.error(
      "[SSG Marketplace] Failed to fetch native integration slugs:",
      error,
    );
    return [];
  }
}

/**
 * Generate static params for all public integrations (community + native).
 * This enables search engines to crawl and index all integration pages.
 * Uses slug for SEO-friendly URLs.
 */
export async function generateStaticParams() {
  const [communityIntegrations, nativeSlugs] = await Promise.all([
    getAllIntegrations(),
    getNativeIntegrationSlugs(),
  ]);

  const communitySlugs = communityIntegrations.map(
    (i: { slug: string }) => i.slug,
  );

  // Deduplicate by slug
  const allSlugs = [...new Set([...communitySlugs, ...nativeSlugs])];

  console.log(
    `[SSG Marketplace] Generating ${allSlugs.length} pages (${communitySlugs.length} community + ${nativeSlugs.length} native)`,
  );
  return allSlugs.map((slug) => ({ slug }));
}

export const dynamicParams = true;

interface Props {
  readonly params: Promise<{ readonly slug: string }>;
}

function generateIntegrationDescription(integration: {
  name: string;
  category: string;
  description?: string;
  toolCount?: number;
}): string {
  const name = integration.name;
  const toolCount = integration.toolCount || 0;
  const toolsNote = toolCount > 0 ? ` ${toolCount} actions available.` : "";

  const categoryDescriptions: Record<string, string> = {
    email: `GAIA reads and triages your ${name} inbox, drafts context-aware replies, auto-labels threads, and creates tasks from emails — automatically, without manual prompts.${toolsNote}`,
    calendar: `GAIA schedules meetings, prepares pre-meeting briefings, finds free slots, and manages your ${name} calendar proactively — triggered by email, conversation, or automation.${toolsNote}`,
    task: `GAIA creates, updates, and prioritizes ${name} tasks automatically from your emails, calendar events, and conversations — no copy-pasting required.${toolsNote}`,
    tasks: `GAIA creates, updates, and prioritizes ${name} tasks automatically from your emails, calendar events, and conversations — no copy-pasting required.${toolsNote}`,
    productivity: `GAIA connects ${name} to your email, calendar, and workflows — automating the repetitive parts so you can focus on deep work.${toolsNote}`,
    communication: `GAIA monitors your ${name} channels, summarizes threads, surfaces what needs your attention, and creates tasks from messages — automatically.${toolsNote}`,
    crm: `GAIA updates ${name} contacts and deals automatically from email threads, meeting notes, and calendar events — keeping your CRM current without manual entry.${toolsNote}`,
    notes: `GAIA saves meeting notes, email summaries, and task context directly to ${name} — automatically building your knowledge base without copy-pasting.${toolsNote}`,
    development: `GAIA creates ${name} issues from email threads, tracks PR status, prepares standup summaries, and syncs your engineering workflow with your calendar.${toolsNote}`,
    automation: `GAIA triggers ${name} workflows from natural language — describe what you want to automate, and GAIA handles the execution across your connected tools.${toolsNote}`,
    storage: `GAIA organizes files and documents in ${name} automatically — saving meeting notes, email attachments, and project artifacts in the right place.${toolsNote}`,
    finance: `GAIA tracks ${name} activity, summarizes transactions, creates follow-up tasks from financial events, and integrates your financial data into your workflow.${toolsNote}`,
    marketing: `GAIA automates ${name} tasks from email campaigns, tracks results, and creates follow-up workflows — connecting your marketing tool to your full productivity stack.${toolsNote}`,
  };

  const categoryKey = integration.category?.toLowerCase();
  if (categoryKey && categoryDescriptions[categoryKey]) {
    return categoryDescriptions[categoryKey];
  }

  return `Connect ${name} to GAIA and automate your workflows with AI. GAIA proactively manages your email, calendar, tasks, and connected tools — including ${name}.${toolsNote} Free MCP integration.`;
}

function generateIntegrationTitle(name: string, category: string): string {
  const categoryTitles: Record<string, string> = {
    email: `${name} AI Email Integration - Triage & Automate ${name} with GAIA`,
    calendar: `${name} AI Calendar Integration - Smart Scheduling with GAIA`,
    task: `${name} AI Task Integration - Create Tasks Automatically with GAIA`,
    tasks: `${name} AI Task Integration - Create Tasks Automatically with GAIA`,
    communication: `${name} AI Integration - Monitor & Automate ${name} with GAIA`,
    crm: `${name} AI CRM Integration - Auto-Update ${name} with GAIA`,
    development: `${name} AI Integration - Automate ${name} Engineering Workflows`,
    notes: `${name} AI Notes Integration - Auto-Save to ${name} with GAIA`,
  };
  const key = category?.toLowerCase();
  return (
    categoryTitles[key] ?? `${name} AI Integration - Automate ${name} with GAIA`
  );
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const integration = await getIntegration(slug);

  if (!integration) {
    return {
      title: "Integration Not Found",
    };
  }

  const url = `${siteConfig.url}/marketplace/${slug}`;
  const ogImage = `/api/og/integration?slug=${slug}`;
  const integrationName = integration.name;
  const categoryLabel =
    integration.category.charAt(0).toUpperCase() +
    integration.category.slice(1);

  const seoDescription = generateIntegrationDescription(integration);

  const title = generateIntegrationTitle(integrationName, integration.category);
  const ogTitle = `${integrationName} AI Integration - Connect ${integrationName} to Your AI Assistant`;

  return {
    title,
    description: seoDescription,
    alternates: {
      canonical: url,
    },
    keywords: [
      integrationName,
      `AI assistant for ${integrationName}`,
      `automate ${integrationName} with AI`,
      `${integrationName} AI automation`,
      `${integrationName} AI integration`,
      `${integrationName} MCP server`,
      `connect ${integrationName} to AI`,
      "MCP integration",
      "AI integration",
      "AI agents",
      "Model Context Protocol",
      `${categoryLabel} AI tools`,
      `${categoryLabel} automation`,
      "GAIA integrations",
      "GAIA",
    ].filter(Boolean),
    openGraph: {
      title: ogTitle,
      description: seoDescription,
      url,
      siteName: siteConfig.fullName,
      images: [{ url: ogImage, width: 1200, height: 630 }],
      type: "website",
    },
    twitter: {
      card: "summary_large_image",
      title: ogTitle,
      description: seoDescription,
      images: [ogImage],
    },
  };
}

export default async function IntegrationPage({ params }: Props) {
  const { slug } = await params;
  const integration = await getIntegration(slug);

  if (!integration) {
    notFound();
  }

  const pageUrl = `${siteConfig.url}/marketplace/${slug}`;
  const categoryLabel =
    integration.category.charAt(0).toUpperCase() +
    integration.category.slice(1);

  // Generate structured data for SEO
  const breadcrumbItems = [
    { name: "Home", url: siteConfig.url },
    { name: "Marketplace", url: `${siteConfig.url}/marketplace` },
    { name: integration.name, url: pageUrl },
  ];

  const breadcrumbSchema = generateBreadcrumbSchema(breadcrumbItems);

  const webPageSchema = generateWebPageSchema(
    `${integration.name} AI Integration - Automate ${integration.name} with AI`,
    `Automate ${integration.name} with GAIA AI assistant. Connect ${integration.name} to your AI-powered workflow with ${integration.toolCount || 0} available tools.`,
    pageUrl,
    breadcrumbItems,
  );

  const integrationSchema = {
    "@context": "https://schema.org" as const,
    "@type": "SoftwareApplication" as const,
    name: `${integration.name} AI Integration`,
    description: integration.description,
    url: pageUrl,
    applicationCategory: "Integration",
    applicationSubCategory: categoryLabel,
    operatingSystem: "Web",
    offers: {
      "@type": "Offer" as const,
      price: "0",
      priceCurrency: "USD",
    },
    ...(integration.creator && {
      author: {
        "@type": "Person" as const,
        name: integration.creator.name,
      },
    }),
    ...(integration.toolCount && {
      featureList: integration.tools
        ?.map((t: { name: string }) => t.name.replace(/_/g, " "))
        .join(", "),
    }),
  };

  const howToSchema = generateHowToSchema(
    `How to automate ${integration.name} with GAIA`,
    `Connect ${integration.name} to GAIA and start automating your ${categoryLabel.toLowerCase()} workflows in plain English — no code required.`,
    [
      {
        name: `Connect ${integration.name} to GAIA`,
        text: `Open the GAIA Marketplace, find the ${integration.name} integration, and click "Add to your GAIA". Authorise access via OAuth or bearer token in under two minutes.`,
      },
      {
        name: "Tell GAIA what to automate in plain English",
        text: `Describe the task you want to automate in natural language. For example: "summarise my ${integration.name} activity every morning" or "notify me on Slack when a new ${categoryLabel.toLowerCase()} event happens in ${integration.name}".`,
      },
      {
        name: "GAIA handles it automatically, 24/7",
        text: `GAIA runs your ${integration.name} automations in the background around the clock, delivering results to you without any manual intervention or scripts to maintain.`,
      },
    ],
  );

  const toolsText =
    integration.toolCount > 0
      ? `all ${integration.toolCount} ${integration.name} tools`
      : `the available ${integration.name} tools`;

  const faqSchema = generateFAQSchema([
    {
      question: `How do I connect ${integration.name} to GAIA?`,
      answer: `Connecting ${integration.name} to GAIA takes under two minutes. Open the GAIA Marketplace, find the ${integration.name} integration, and click "Add to your GAIA". Depending on the integration type, you will be redirected to an OAuth consent screen or asked to paste a bearer token. Once authorised, GAIA immediately gains access to all ${integration.name} tools.`,
    },
    {
      question: `Is the ${integration.name} integration free?`,
      answer: `Yes. GAIA offers a generous free tier that includes access to community integrations like ${integration.name}. You can connect ${integration.name}, run automations, and use all available tools at no cost. Paid plans unlock higher usage limits and advanced workflow features.`,
    },
    {
      question: `What can GAIA do with ${integration.name}?`,
      answer: `GAIA exposes ${toolsText} to its AI agent, meaning you can perform any ${categoryLabel.toLowerCase()} action supported by ${integration.name} by describing it in plain English. GAIA can also combine ${integration.name} with other connected integrations to build cross-tool automations.`,
    },
    {
      question: `Does GAIA's ${integration.name} integration work on mobile?`,
      answer: `Absolutely. GAIA runs on web, desktop (macOS and Windows), and mobile (iOS and Android). Your ${integration.name} integration is available across all platforms with your account.`,
    },
  ]);

  const comparisonSlug = getComparison(slug) ? slug : undefined;

  return (
    <>
      <JsonLd
        data={[
          webPageSchema,
          breadcrumbSchema,
          integrationSchema,
          howToSchema,
          faqSchema,
        ]}
      />
      <IntegrationDetailClient
        integration={integration}
        comparisonSlug={comparisonSlug}
      />
    </>
  );
}
