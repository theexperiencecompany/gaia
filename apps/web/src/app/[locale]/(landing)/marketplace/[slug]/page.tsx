import type { IntegrationsConfigResponse } from "@shared/api/generated";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import JsonLd from "@/components/seo/JsonLd";
import { getComparison } from "@/features/comparisons/data/comparisonsData";
import type {
  CommunityIntegration,
  CommunityIntegrationsResponse,
  PublicIntegrationResponse,
} from "@/features/integrations/types";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateHowToSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";

import { IntegrationDetailClient } from "./client";
import { getIntegrationFAQs } from "./faqs";
import {
  generateIntegrationDescription,
  generateIntegrationTitle,
} from "./integrationMeta";

export const revalidate = 60;

// Fetch integration data for metadata and page
// Backend accepts both slug and UUID for backward compatibility
const getIntegration = cache(
  async (slug: string): Promise<PublicIntegrationResponse | null> => {
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
      return (await response.json()) as PublicIntegrationResponse;
    } catch (error) {
      console.error(
        `[marketplace/${slug}] Failed to fetch integration:`,
        error,
      );
      return null;
    }
  },
);

// Fetch all integrations for static generation
async function getAllIntegrations(): Promise<CommunityIntegration[]> {
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
      const data = (await response.json()) as CommunityIntegrationsResponse;
      return data.integrations ?? [];
    }

    const { fetchAllPaginated } = await import("@/lib/fetchAll");
    const allIntegrations = await fetchAllPaginated<CommunityIntegration>(
      async (limit, offset) => {
        const response = await fetch(
          `${baseUrl}/integrations/community?limit=${limit}&offset=${offset}`,
          { next: { revalidate: 60 } },
        );
        if (!response.ok) return { items: [], total: 0, hasMore: false };

        const data = (await response.json()) as CommunityIntegrationsResponse;
        return {
          items: data.integrations ?? [],
          total: data.total ?? 0,
          hasMore: data.has_more !== false,
        };
      },
      100,
    );

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
    const data = (await response.json()) as IntegrationsConfigResponse;
    const slugs: string[] = [];
    for (const integration of data.integrations) {
      if (integration.id && integration.available !== false) {
        slugs.push(integration.id);
      }
    }
    return slugs;
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
  return allSlugs.map((slug) => ({ slug }));
}

export const dynamicParams = true;

interface Props {
  readonly params: Promise<{ readonly slug: string }>;
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
  // Independent fetches — run in parallel to save a round-trip on the happy path.
  const [integration, comparison] = await Promise.all([
    getIntegration(slug),
    getComparison(slug),
  ]);

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
    integration.publishedAt ?? undefined,
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
    ...(integration.creator?.name && {
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
    `Connect ${integration.name} to GAIA and start automating your ${categoryLabel.toLowerCase()} workflows in plain English, no code required.`,
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

  // Same source as the visible accordion in IntegrationRichContent —
  // the FAQ rich snippet must match what visitors actually see.
  const faqSchema = generateFAQSchema(getIntegrationFAQs(integration));

  const comparisonSlug = comparison ? slug : undefined;

  // Same-category siblings and related workflows, fetched server-side so
  // crawlers see real links in the SSR HTML instead of client-only orphans.
  const [relatedIntegrations, relatedWorkflows] = await Promise.all([
    getRelatedIntegrations(integration.category, slug),
    getRelatedWorkflows(integration.integrationId),
  ]);

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
        initialRelatedIntegrations={relatedIntegrations}
        initialRelatedWorkflows={relatedWorkflows}
      />
    </>
  );
}

/** Same-category siblings for SSR related-links (excludes the current page). */
async function getRelatedIntegrations(
  category: string,
  slug: string,
): Promise<CommunityIntegration[]> {
  const baseUrl = getServerApiBaseUrl();
  if (!baseUrl) return [];

  try {
    const response = await fetch(
      `${baseUrl}/integrations/community?category=${encodeURIComponent(category)}&sort=popular&limit=7`,
      { next: { revalidate: 60 } },
    );
    if (!response.ok) return [];
    const data = (await response.json()) as CommunityIntegrationsResponse;
    return (data.integrations ?? [])
      .filter((integration) => integration.slug !== slug)
      .slice(0, 6);
  } catch (error) {
    console.error(
      `[marketplace/${slug}] Failed to fetch related integrations:`,
      error,
    );
    return [];
  }
}

/** Community workflows using this integration, for SSR related-links. */
async function getRelatedWorkflows(
  integrationId: string,
): Promise<CommunityWorkflow[]> {
  const baseUrl = getServerApiBaseUrl();
  if (!baseUrl) return [];

  try {
    const response = await fetch(
      `${baseUrl}/integrations/public/${encodeURIComponent(integrationId)}/workflows?limit=4`,
      { next: { revalidate: 60 } },
    );
    if (!response.ok) return [];
    const data = (await response.json()) as {
      workflows?: CommunityWorkflow[];
    };
    return (data.workflows ?? []).slice(0, 4);
  } catch (error) {
    console.error(
      `[marketplace/${integrationId}] Failed to fetch related workflows:`,
      error,
    );
    return [];
  }
}
