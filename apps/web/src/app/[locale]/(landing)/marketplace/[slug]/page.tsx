import "../../../../styles/content.css";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import JsonLd from "@/components/seo/JsonLd";
import { getTranslatedAlternative } from "@/features/alternatives/data/getTranslatedAlternative";
import { getComparison } from "@/features/comparisons/data/comparisonsData";
import { getAllCombos } from "@/features/integrations/data/combosData";
import {
  marketplaceDirectoryHref,
  marketplaceDirectoryPages,
} from "@/features/integrations/lib/marketplaceDirectoryPages";
import {
  marketplacePath,
  marketplaceSlug,
} from "@/features/integrations/lib/marketplaceSlug";
import { relatedIntegrations } from "@/features/integrations/lib/relatedIntegrations";
import {
  getAllCommunityIntegrations,
  getIntegrationWorkflows,
  getNativeIntegrations,
  getPublicIntegration,
  marketplaceApiIdentifier,
} from "@/features/integrations/lib/serverMarketplaceApi";
import type { PublicIntegrationResponse } from "@/features/integrations/types";
import { WorkflowIconElementsProvider } from "@/features/workflows/components/shared/WorkflowIconElements";
import { workflowIconElements } from "@/features/workflows/lib/workflowIconElements";
import { isRedirectedPath } from "@/lib/canonicalLinks";
import {
  getMarketplaceFallbackGuides,
  MARKETPLACE_DOCS_LINKS,
} from "@/lib/docs-links";
import { prerenderedMarketingParams } from "@/lib/selfhost";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateHowToSchema,
  generatePageMetadata,
  generateProOffer,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { IntegrationDetailClient } from "./client";
import { IntegrationToolsCard } from "./IntegrationToolsCard";
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
async function allStaticParams() {
  const [native, community] = await Promise.all([
    getNativeIntegrations(),
    getAllCommunityIntegrations(),
  ]);
  const slugs = new Set(
    [...native, ...community].map((item) => marketplaceSlug(item.slug)),
  );
  return [...slugs].map((slug) => ({ slug }));
}

export function generateStaticParams() {
  return prerenderedMarketingParams(allStaticParams);
}

export const dynamicParams = true;

interface Props {
  readonly params: Promise<{ readonly slug: string }>;
}

/** The integration a marketplace URL slug names; the API is keyed by its own slug. */
async function integrationAtSlug(
  slug: string,
): Promise<PublicIntegrationResponse | null> {
  return getPublicIntegration(await marketplaceApiIdentifier(slug));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const integration = await integrationAtSlug(slug);

  if (!integration) {
    return {
      title: "Integration Not Found",
    };
  }

  const integrationName = integration.name;
  const categoryLabel =
    integration.category.charAt(0).toUpperCase() +
    integration.category.slice(1);

  return generatePageMetadata({
    title: generateIntegrationTitle(integration),
    description: generateIntegrationDescription(integration),
    path: marketplacePath(integration.slug),
    image: `/api/og/integration?slug=${integration.slug}`,
    keywords: [
      integrationName,
      `AI assistant for ${integrationName}`,
      `automate ${integrationName} with AI`,
      `${integrationName} AI automation`,
      `${integrationName} AI integration`,
      `${integrationName} MCP server`,
      `connect ${integrationName} to AI`,
      "MCP integration",
      "Model Context Protocol",
      `${categoryLabel} AI tools`,
      `${categoryLabel} automation`,
      "GAIA integrations",
    ],
  });
}

export default async function IntegrationPage({ params }: Props) {
  const { slug } = await params;
  // Independent fetches — run in parallel to save a round-trip on the happy path.
  const [integration, comparison] = await Promise.all([
    integrationAtSlug(slug),
    getComparison(slug),
  ]);

  if (!integration) {
    notFound();
  }

  const pageUrl = `${siteConfig.url}${marketplacePath(integration.slug)}`;
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

  // The page's own title and description, so two integrations sharing a name stay two pages.
  const webPageSchema = generateWebPageSchema(
    generateIntegrationTitle(integration),
    generateIntegrationDescription(integration),
    pageUrl,
    breadcrumbItems,
    integration.publishedAt
      ? {
          published: integration.publishedAt,
          modified: integration.publishedAt,
        }
      : undefined,
  );

  const integrationSchema = {
    "@context": "https://schema.org" as const,
    "@type": "SoftwareApplication" as const,
    "@id": `${pageUrl}#integration`,
    name: `${integration.name} AI Integration`,
    description: integration.description,
    url: pageUrl,
    applicationCategory: "Integration",
    applicationSubCategory: categoryLabel,
    operatingSystem: "Web",
    offers: generateProOffer(),
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

  // Related integrations and workflows are fetched server-side so crawlers
  // see real links in the SSR HTML. Combos and the alternative guide come from
  // local JSON (no backend).
  const [native, community, relatedWorkflows, automateCombos, alternative] =
    await Promise.all([
      getNativeIntegrations(),
      // Natives come first in the directory, so a native page needs no community data.
      integration.source === "platform" ? [] : getAllCommunityIntegrations(),
      getIntegrationWorkflows(integration.integrationId, 4),
      getAutomateCombos(slug),
      getTranslatedAlternative(slug),
    ]);
  // A native page relates only to natives (community is empty for it).
  const related = relatedIntegrations(integration, native, community);
  const directoryHref = marketplaceDirectoryHref(
    marketplaceDirectoryPages(native, community),
    integration.slug,
  );

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
      <WorkflowIconElementsProvider
        icons={workflowIconElements(relatedWorkflows)}
      >
        <IntegrationDetailClient
          integration={integration}
          toolsCard={<IntegrationToolsCard integration={integration} />}
          comparisonSlug={comparisonSlug}
          alternativeSlug={
            alternative && !isRedirectedPath(`/alternative-to/${slug}`)
              ? slug
              : undefined
          }
          relatedIntegrations={related}
          directoryHref={directoryHref}
          initialRelatedWorkflows={relatedWorkflows}
          automateCombos={automateCombos}
          docsGuides={
            MARKETPLACE_DOCS_LINKS[slug] ?? getMarketplaceFallbackGuides()
          }
        />
      </WorkflowIconElementsProvider>
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
