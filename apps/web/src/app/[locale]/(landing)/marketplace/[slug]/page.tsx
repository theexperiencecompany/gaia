import type { Metadata } from "next";
import { notFound } from "next/navigation";
import JsonLd from "@/components/seo/JsonLd";
import { getTranslatedAlternative } from "@/features/alternatives/data/getTranslatedAlternative";
import { getComparison } from "@/features/comparisons/data/comparisonsData";
import { getAllCombos } from "@/features/integrations/data/combosData";
import {
  getAllCommunityIntegrations,
  getCommunityIntegrations,
  getIntegrationWorkflows,
  getNativeIntegrations,
  getPublicIntegration,
} from "@/features/integrations/data/marketplaceServer";
import type { CommunityIntegration } from "@/features/integrations/types";
import { isRedirectedPath } from "@/lib/canonicalLinks";
import {
  getMarketplaceFallbackGuides,
  MARKETPLACE_DOCS_LINKS,
} from "@/lib/docs-links";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateHowToSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { IntegrationDetailClient } from "./client";
import {
  generateIntegrationDescription,
  generateIntegrationTitle,
} from "./integrationMeta";

export const revalidate = 60;

/**
 * Generate static params for all public integrations (community + native).
 * This enables search engines to crawl and index all integration pages.
 * Uses slug for SEO-friendly URLs.
 */
export async function generateStaticParams() {
  const [native, community] = await Promise.all([
    getNativeIntegrations(),
    getAllCommunityIntegrations(),
  ]);
  const slugs = new Set([...native, ...community].map((item) => item.slug));
  return [...slugs].map((slug) => ({ slug }));
}

export const dynamicParams = true;

interface Props {
  readonly params: Promise<{ readonly slug: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const integration = await getPublicIntegration(slug);

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

  const title = generateIntegrationTitle(
    integrationName,
    integration.category,
    slug,
  );
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
    getPublicIntegration(slug),
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

  // Both schemas mirror the stored content the page renders, and are omitted with it.
  const { howItWorks = [], faqs = [] } = integration.content ?? {};
  const contentSchemas = [
    ...(howItWorks.length > 0
      ? [
          generateHowToSchema(
            `How to automate ${integration.name} with GAIA`,
            `Connect ${integration.name} to GAIA and automate it in plain English, no code required.`,
            howItWorks.map((step) => ({ name: step.title, text: step.body })),
          ),
        ]
      : []),
    ...(faqs.length > 0 ? [generateFAQSchema(faqs)] : []),
  ];

  const comparisonSlug =
    comparison && !isRedirectedPath(`/compare/${slug}`) ? slug : undefined;

  // Same-category siblings and related workflows, fetched server-side so
  // crawlers see real links in the SSR HTML instead of client-only orphans.
  // Combos and the alternative guide come from local JSON (no backend).
  const [relatedIntegrations, relatedWorkflows, automateCombos, alternative] =
    await Promise.all([
      getRelatedIntegrations(integration.category, slug),
      getIntegrationWorkflows(integration.integrationId, 4),
      getAutomateCombos(slug),
      getTranslatedAlternative(slug),
    ]);

  return (
    <>
      <JsonLd
        data={[
          webPageSchema,
          breadcrumbSchema,
          integrationSchema,
          ...contentSchemas,
        ]}
      />
      <IntegrationDetailClient
        integration={integration}
        comparisonSlug={comparisonSlug}
        alternativeSlug={
          alternative && !isRedirectedPath(`/alternative-to/${slug}`)
            ? slug
            : undefined
        }
        initialRelatedIntegrations={relatedIntegrations}
        initialRelatedWorkflows={relatedWorkflows}
        automateCombos={automateCombos}
        docsGuides={
          MARKETPLACE_DOCS_LINKS[slug] ?? getMarketplaceFallbackGuides()
        }
      />
    </>
  );
}

/** Automate combos featuring this tool. The list is _slugs-driven, so
 * consolidated victims never appear — no marker filter needed. */
async function getAutomateCombos(
  slug: string,
): Promise<
  Array<{ slug: string; toolA: string; toolB: string; tagline: string }>
> {
  const combos = await getAllCombos();
  return combos
    .filter((combo) => combo.toolASlug === slug || combo.toolBSlug === slug)
    .slice(0, 6)
    .map((combo) => ({
      slug: combo.slug,
      toolA: combo.toolA,
      toolB: combo.toolB,
      tagline: combo.tagline,
    }));
}

/** Same-category siblings for SSR related-links (excludes the current page). */
async function getRelatedIntegrations(
  category: string,
  slug: string,
): Promise<CommunityIntegration[]> {
  const page = await getCommunityIntegrations({
    category,
    sort: "popular",
    limit: 7,
  });
  return (page?.integrations ?? [])
    .filter((integration) => integration.slug !== slug)
    .slice(0, 6);
}
